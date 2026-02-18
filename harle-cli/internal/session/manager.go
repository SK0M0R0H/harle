package session

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/skm/harle/harle-cli/internal/client"
)

type Manager struct {
	Client         *client.HTTPClient
	Context        string
	conversationID *string
}

func NewManager(httpClient *client.HTTPClient, contextValue string) *Manager {
	return &Manager{
		Client:  httpClient,
		Context: contextValue,
	}
}

func (m *Manager) Run(ctx context.Context) error {
	fmt.Printf("Harle v0.2.0 | context: %s\n", m.Context)
	fmt.Println("Type a message, /help, or /quit.")

	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Print("harle> ")
		if !scanner.Scan() {
			fmt.Println()
			return nil
		}

		input := strings.TrimSpace(scanner.Text())
		if input == "" {
			continue
		}

		if m.handleSlashCommand(input) {
			continue
		}

		response, err := m.Client.Chat(
			ctx,
			client.RunRequest{
				Message:        input,
				Context:        m.Context,
				ConversationID: m.conversationID,
			},
		)
		if err != nil {
			fmt.Printf("Error: %v\n", err)
			continue
		}

		if response.ConversationID != nil {
			m.conversationID = response.ConversationID
		}

		fmt.Println(response.Result)
	}
}

func (m *Manager) handleSlashCommand(input string) bool {
	switch input {
	case "/quit", "/exit":
		fmt.Println("Session closed.")
		os.Exit(0)
	case "/new":
		m.conversationID = nil
		fmt.Println("New conversation started.")
	case "/id":
		if m.conversationID != nil {
			fmt.Printf("conversation: %s\n", *m.conversationID)
		} else {
			fmt.Println("No active conversation yet.")
		}
	case "/help":
		fmt.Println("Slash commands:")
		fmt.Println("  /new   — start a new conversation")
		fmt.Println("  /id    — show current conversation ID")
		fmt.Println("  /help  — show this help")
		fmt.Println("  /quit  — close the session")
	default:
		if strings.HasPrefix(input, "/") {
			fmt.Printf("Unknown command: %s (type /help)\n", input)
			return true
		}
		return false
	}
	return true
}
