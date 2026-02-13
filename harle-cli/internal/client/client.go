package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type HTTPClient struct {
	BaseURL string
	Client  *http.Client
}

func NewHTTPClient(baseURL string) *HTTPClient {
	return &HTTPClient{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Client: &http.Client{
			Timeout: 120 * time.Second,
		},
	}
}

func (h *HTTPClient) Run(ctx context.Context, request RunRequest) (RunResponse, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return RunResponse{}, fmt.Errorf("marshal request: %w", err)
	}

	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BaseURL+"/run", bytes.NewReader(body))
	if err != nil {
		return RunResponse{}, fmt.Errorf("build request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json")

	httpResponse, err := h.Client.Do(httpRequest)
	if err != nil {
		return RunResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	if httpResponse.StatusCode >= 300 {
		responseBody, _ := io.ReadAll(httpResponse.Body)
		return RunResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, string(responseBody))
	}

	var response RunResponse
	if err := json.NewDecoder(httpResponse.Body).Decode(&response); err != nil {
		return RunResponse{}, fmt.Errorf("decode response: %w", err)
	}

	return response, nil
}
