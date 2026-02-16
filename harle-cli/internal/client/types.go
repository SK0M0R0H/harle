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

type InitResponse struct {
	Status        string `json:"status"`
	TablesCreated bool   `json:"tables_created"`
	FilesSeeded   int    `json:"files_seeded"`
	FilesIndexed  int    `json:"files_indexed"`
	TotalFiles    int    `json:"total_files"`
	DatasetPath   string `json:"dataset_path"`
}
