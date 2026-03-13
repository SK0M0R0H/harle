package client

// InterviewStartRequest is sent to POST /capture/interview/start.
type InterviewStartRequest struct {
	Scope  string `json:"scope"`
	Tiers  []int  `json:"tiers"`
	Resume bool   `json:"resume"`
}

// InterviewRespondRequest is sent to POST /capture/interview/respond.
type InterviewRespondRequest struct {
	RunID    string `json:"run_id"`
	Response string `json:"response"`
	Action   string `json:"action"`
}

// InterviewProgress holds progress statistics.
type InterviewProgress struct {
	Completed   int  `json:"completed"`
	Skipped     int  `json:"skipped"`
	Total       int  `json:"total"`
	CurrentTier *int `json:"current_tier"`
}

// InterviewResponse is returned by interview endpoints.
type InterviewResponse struct {
	RunID          string            `json:"run_id"`
	Action         string            `json:"action"`
	Message        string            `json:"message"`
	TopicID        *string           `json:"topic_id"`
	TopicName      *string           `json:"topic_name"`
	DraftContent   *string           `json:"draft_content"`
	CapabilityNote *string           `json:"capability_note"`
	Progress       InterviewProgress `json:"progress"`
}
