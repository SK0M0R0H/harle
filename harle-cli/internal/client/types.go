package client

type RunRequest struct {
	Message        string  `json:"message"`
	Context        string  `json:"context"`
	ConversationID *string `json:"conversation_id"`
}

type RunResponse struct {
	RunID          string   `json:"run_id"`
	Status         string   `json:"status"`
	Result         string   `json:"result"`
	Context        string   `json:"context"`
	Agent          string   `json:"agent"`
	ConversationID *string  `json:"conversation_id"`
	ToolsCalled    []string `json:"tools_called"`
	TurnsUsed      *int     `json:"turns_used"`
}

type InitResponse struct {
	Status        string `json:"status"`
	TablesCreated bool   `json:"tables_created"`
	FilesSeeded   int    `json:"files_seeded"`
	FilesIndexed  int    `json:"files_indexed"`
	TotalFiles    int    `json:"total_files"`
	DatasetPath   string `json:"dataset_path"`
}

type ImportRequest struct {
	Source string            `json:"source"`
	Config map[string]string `json:"config"`
	DryRun bool              `json:"dry_run"`
}

type ImportResponse struct {
	Status        string   `json:"status"`
	Source        string   `json:"source"`
	ItemsFound    int      `json:"items_found"`
	ItemsImported int      `json:"items_imported"`
	ItemsSkipped  int      `json:"items_skipped"`
	ItemsFailed   int      `json:"items_failed"`
	Errors        []string `json:"errors"`
	CreatedPaths  []string `json:"created_paths"`
	UpdatedPaths  []string `json:"updated_paths"`
}
