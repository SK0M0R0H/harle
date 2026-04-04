package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// InterviewStart calls POST /capture/interview/start.
func (h *HTTPClient) InterviewStart(ctx context.Context, request InterviewStartRequest) (InterviewResponse, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return InterviewResponse{}, fmt.Errorf("marshal request: %w", err)
	}

	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BaseURL+"/capture/interview/start", bytes.NewReader(body))
	if err != nil {
		return InterviewResponse{}, fmt.Errorf("build request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json")
	h.setAuthHeaders(httpRequest)

	httpResponse, err := h.Client.Do(httpRequest)
	if err != nil {
		return InterviewResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	if httpResponse.StatusCode >= 300 {
		responseBody, _ := io.ReadAll(httpResponse.Body)
		return InterviewResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, string(responseBody))
	}

	var response InterviewResponse
	if err := json.NewDecoder(httpResponse.Body).Decode(&response); err != nil {
		return InterviewResponse{}, fmt.Errorf("decode response: %w", err)
	}
	return response, nil
}

// InterviewRespond calls POST /capture/interview/respond.
func (h *HTTPClient) InterviewRespond(ctx context.Context, request InterviewRespondRequest) (InterviewResponse, error) {
	body, err := json.Marshal(request)
	if err != nil {
		return InterviewResponse{}, fmt.Errorf("marshal request: %w", err)
	}

	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BaseURL+"/capture/interview/respond", bytes.NewReader(body))
	if err != nil {
		return InterviewResponse{}, fmt.Errorf("build request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json")
	h.setAuthHeaders(httpRequest)

	httpResponse, err := h.Client.Do(httpRequest)
	if err != nil {
		return InterviewResponse{}, fmt.Errorf("request failed: %w", err)
	}
	defer httpResponse.Body.Close()

	if httpResponse.StatusCode >= 300 {
		responseBody, _ := io.ReadAll(httpResponse.Body)
		return InterviewResponse{}, fmt.Errorf("server returned %d: %s", httpResponse.StatusCode, string(responseBody))
	}

	var response InterviewResponse
	if err := json.NewDecoder(httpResponse.Body).Decode(&response); err != nil {
		return InterviewResponse{}, fmt.Errorf("decode response: %w", err)
	}
	return response, nil
}
