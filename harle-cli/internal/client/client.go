package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const processingPingTimeout = 10 * time.Second

// ErrChatServerTimeout is returned when POST /chat responds with HTTP 504 (server run wall-clock limit).
var ErrChatServerTimeout = errors.New("server timed out processing the chat request")

// IsChatServerTimeout reports whether err wraps ErrChatServerTimeout from Chat.
func IsChatServerTimeout(err error) bool {
	return err != nil && errors.Is(err, ErrChatServerTimeout)
}

const harleClientHeader = "X-Harle-Client"
const harleClientValue = "harle-cli"

type HTTPClient struct {
	BaseURL   string
	APIToken  string
	Client    *http.Client // short-lived requests: /init, /import, processing pings use ad-hoc 10s in CheckProcessing
	LongClient *http.Client // no deadline; POST /chat only
}

func NewHTTPClient(baseURL, apiToken string) *HTTPClient {
	return &HTTPClient{
		BaseURL:  strings.TrimRight(baseURL, "/"),
		APIToken: strings.TrimSpace(apiToken),
		Client: &http.Client{
			Timeout: 120 * time.Second,
		},
		LongClient: &http.Client{
			Timeout: 0,
		},
	}
}

func (h *HTTPClient) setAuthHeaders(req *http.Request) {
	req.Header.Set(harleClientHeader, harleClientValue)
	if h.APIToken != "" {
		req.Header.Set("Authorization", "Bearer "+h.APIToken)
	}
}

// Chat posts to /chat. If requestID is non-empty, sends X-Request-ID for server-side processing tracking.
func (h *HTTPClient) Chat(ctx context.Context, request RunRequest, requestID string) (RunResponse, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return RunResponse{}, fmt.Errorf("marshal request: %w", err)
	}

	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BaseURL+"/chat", bytes.NewReader(body))
	if err != nil {
		return RunResponse{}, fmt.Errorf("build request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json")
	h.setAuthHeaders(httpRequest)
	if requestID != "" {
		httpRequest.Header.Set("X-Request-ID", requestID)
	}

	hc := h.LongClient
	if hc == nil {
		hc = h.Client
	}
	httpResponse, err := hc.Do(httpRequest)
	if err != nil {
		return RunResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	if httpResponse.StatusCode >= 300 {
		responseBody, _ := io.ReadAll(httpResponse.Body)
		body := strings.TrimSpace(string(responseBody))
		if httpResponse.StatusCode == http.StatusGatewayTimeout {
			return RunResponse{}, fmt.Errorf("%w: %s", ErrChatServerTimeout, body)
		}
		return RunResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, body)
	}

	var response RunResponse
	if err := json.NewDecoder(httpResponse.Body).Decode(&response); err != nil {
		return RunResponse{}, fmt.Errorf("decode response: %w", err)
	}

	return response, nil
}

// CheckProcessing asks GET /processing/{requestID} (short HTTP timeout).
func (h *HTTPClient) CheckProcessing(ctx context.Context, requestID string) (ProcessingStatusResponse, error) {
	base, err := url.Parse(h.BaseURL)
	if err != nil {
		return ProcessingStatusResponse{}, fmt.Errorf("parse base URL: %w", err)
	}
	full := base.JoinPath("processing", requestID).String()
	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodGet, full, nil)
	if err != nil {
		return ProcessingStatusResponse{}, fmt.Errorf("build request: %w", err)
	}
	h.setAuthHeaders(httpRequest)
	pingClient := &http.Client{Timeout: processingPingTimeout}
	httpResponse, err := pingClient.Do(httpRequest)
	if err != nil {
		return ProcessingStatusResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	body, err := io.ReadAll(httpResponse.Body)
	if err != nil {
		return ProcessingStatusResponse{}, fmt.Errorf("read response: %w", err)
	}
	if httpResponse.StatusCode >= 300 {
		return ProcessingStatusResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, string(body))
	}

	var out ProcessingStatusResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return ProcessingStatusResponse{}, fmt.Errorf("decode response: %w", err)
	}
	return out, nil
}

func (h *HTTPClient) Import(ctx context.Context, request ImportRequest) (ImportResponse, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("marshal request: %w", err)
	}

	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BaseURL+"/import", bytes.NewReader(body))
	if err != nil {
		return ImportResponse{}, fmt.Errorf("build request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json")
	h.setAuthHeaders(httpRequest)

	httpResponse, err := h.Client.Do(httpRequest)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	if httpResponse.StatusCode >= 300 {
		responseBody, _ := io.ReadAll(httpResponse.Body)
		return ImportResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, string(responseBody))
	}

	var response ImportResponse
	if err := json.NewDecoder(httpResponse.Body).Decode(&response); err != nil {
		return ImportResponse{}, fmt.Errorf("decode response: %w", err)
	}

	return response, nil
}

func (h *HTTPClient) Init(ctx context.Context) (InitResponse, error) {
	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BaseURL+"/init", nil)
	if err != nil {
		return InitResponse{}, fmt.Errorf("build request: %w", err)
	}
	h.setAuthHeaders(httpRequest)

	httpResponse, err := h.Client.Do(httpRequest)
	if err != nil {
		return InitResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	if httpResponse.StatusCode >= 300 {
		responseBody, _ := io.ReadAll(httpResponse.Body)
		return InitResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, string(responseBody))
	}

	var response InitResponse
	if err := json.NewDecoder(httpResponse.Body).Decode(&response); err != nil {
		return InitResponse{}, fmt.Errorf("decode response: %w", err)
	}

	return response, nil
}
