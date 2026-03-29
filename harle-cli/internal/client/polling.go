package client

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"
	"time"

	"github.com/google/uuid"
)

// Errors returned by ChatWithPolling for distinct UX messaging.
var (
	ErrServerUnreachable = errors.New("server became unreachable while processing your request")
	ErrProcessingLost    = errors.New("server reports this chat request is no longer in progress")
)

// PollConfig drives periodic GET /processing/{id} while POST /chat is in flight.
type PollConfig struct {
	PingInterval   time.Duration
	MaxMissedPings int
	GracePeriod    time.Duration
	// MaxWait is an optional client-side wall-clock cap for the whole operation (0 = unlimited).
	MaxWait time.Duration
	// ProgressWriter receives a short line after each successful "processing" ping (e.g. os.Stderr).
	ProgressWriter io.Writer
}

// DefaultPollConfig matches server run timeouts in the 60–120s range with margin.
func DefaultPollConfig() PollConfig {
	return PollConfig{
		PingInterval:   15 * time.Second,
		MaxMissedPings: 3,
		GracePeriod:    5 * time.Second,
		MaxWait:        0,
		ProgressWriter: nil,
	}
}

// PollConfigFromEnvironment overlays HARLE_CHAT_* env vars on DefaultPollConfig.
//
//	HARLE_CHAT_PING_INTERVAL_SECONDS
//	HARLE_CHAT_GRACE_PERIOD_SECONDS
//	HARLE_CHAT_MAX_MISSED_PINGS
//	HARLE_CHAT_MAX_WAIT_SECONDS (0 or unset = unlimited)
//	HARLE_CHAT_SHOW_PROGRESS (1/true/yes → ProgressWriter = os.Stderr)
func PollConfigFromEnvironment() PollConfig {
	c := DefaultPollConfig()
	if s := os.Getenv("HARLE_CHAT_PING_INTERVAL_SECONDS"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			c.PingInterval = time.Duration(n) * time.Second
		}
	}
	if s := os.Getenv("HARLE_CHAT_GRACE_PERIOD_SECONDS"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n >= 0 {
			c.GracePeriod = time.Duration(n) * time.Second
		}
	}
	if s := os.Getenv("HARLE_CHAT_MAX_MISSED_PINGS"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			c.MaxMissedPings = n
		}
	}
	if s := os.Getenv("HARLE_CHAT_MAX_WAIT_SECONDS"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			c.MaxWait = time.Duration(n) * time.Second
		}
	}
	if truthyEnv(os.Getenv("HARLE_CHAT_SHOW_PROGRESS")) {
		c.ProgressWriter = os.Stderr
	}
	return c
}

func truthyEnv(s string) bool {
	switch s {
	case "1", "true", "True", "yes", "YES", "on", "ON":
		return true
	default:
		return false
	}
}

type chatResult struct {
	resp RunResponse
	err  error
}

// ChatWithPolling runs POST /chat without a client-side HTTP deadline and pings
// GET /processing/{request_id} until the chat completes or a stop condition triggers.
func (h *HTTPClient) ChatWithPolling(ctx context.Context, request RunRequest, cfg PollConfig) (RunResponse, error) {
	if cfg.PingInterval <= 0 {
		cfg.PingInterval = DefaultPollConfig().PingInterval
	}
	if cfg.MaxMissedPings <= 0 {
		cfg.MaxMissedPings = DefaultPollConfig().MaxMissedPings
	}
	if cfg.GracePeriod < 0 {
		cfg.GracePeriod = 0
	}

	if cfg.MaxWait > 0 {
		var cancelWait context.CancelFunc
		ctx, cancelWait = context.WithTimeout(ctx, cfg.MaxWait)
		defer cancelWait()
	}

	requestID := uuid.New().String()
	chatCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	resultCh := make(chan chatResult, 1)
	go func() {
		resp, err := h.Chat(chatCtx, request, requestID)
		resultCh <- chatResult{resp, err}
	}()

	if cfg.GracePeriod > 0 {
		select {
		case r := <-resultCh:
			return r.resp, r.err
		case <-time.After(cfg.GracePeriod):
		case <-ctx.Done():
			cancel()
			<-resultCh
			return RunResponse{}, ctx.Err()
		}
	} else {
		select {
		case r := <-resultCh:
			return r.resp, r.err
		case <-ctx.Done():
			cancel()
			<-resultCh
			return RunResponse{}, ctx.Err()
		default:
		}
	}

	pingTimer := time.NewTimer(0)
	defer pingTimer.Stop()

	missedPings := 0
	notFoundStreak := 0

	for {
		select {
		case r := <-resultCh:
			return r.resp, r.err
		case <-ctx.Done():
			cancel()
			<-resultCh
			return RunResponse{}, ctx.Err()
		case <-pingTimer.C:
			if !pingTimer.Stop() {
				select {
				case <-pingTimer.C:
				default:
				}
			}
			pingTimer.Reset(cfg.PingInterval)

			status, err := h.CheckProcessing(ctx, requestID)
			if err != nil {
				missedPings++
				if missedPings >= cfg.MaxMissedPings {
					cancel()
					select {
					case r := <-resultCh:
						if r.err != nil && errors.Is(r.err, context.Canceled) {
							return RunResponse{}, fmt.Errorf("%w: %v", ErrServerUnreachable, err)
						}
						return r.resp, r.err
					case <-time.After(30 * time.Second):
						return RunResponse{}, fmt.Errorf("%w: %v", ErrServerUnreachable, err)
					}
				}
				continue
			}
			missedPings = 0

			switch status.Status {
			case "processing":
				notFoundStreak = 0
				if cfg.ProgressWriter != nil {
					_, _ = fmt.Fprintf(
						cfg.ProgressWriter,
						"\r[%s] Still working… server reports request in progress\n",
						time.Now().Format("15:04:05"),
					)
				}
			case "not_found":
				notFoundStreak++
				if notFoundStreak >= 2 {
					cancel()
					select {
					case r := <-resultCh:
						if r.err == nil {
							return r.resp, nil
						}
						if errors.Is(r.err, context.Canceled) {
							return RunResponse{}, ErrProcessingLost
						}
						return r.resp, r.err
					case <-time.After(30 * time.Second):
						return RunResponse{}, ErrProcessingLost
					}
				}
			default:
				notFoundStreak = 0
			}
		}
	}
}
