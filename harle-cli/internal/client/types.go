package client

type RunRequest struct {
	Message        string  `json:"message"`
	Context        string  `json:"context"`
	ConversationID *string `json:"conversation_id"`
}

type RunResponse struct {
	RunID          string  `json:"run_id"`
	Status         string  `json:"status"`
	Result         string  `json:"result"`
	Context        string  `json:"context"`
	ConversationID *string `json:"conversation_id"`
}
