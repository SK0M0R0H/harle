package session

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/skm/harle/harle-cli/internal/render"
)

type Manager struct {
	Client         *client.HTTPClient
	Context        string
	Theme          string
	conversationID *string
	renderer       *render.Renderer
}

func NewManager(httpClient *client.HTTPClient, contextValue string, theme string) *Manager {
	return &Manager{
		Client:   httpClient,
		Context:  contextValue,
		Theme:    theme,
		renderer: render.NewRenderer(theme),
	}
}

func (m *Manager) Run(ctx context.Context) error {
	fmt.Println(m.renderer.Header("Harle v0.2.0"), m.renderer.Muted(fmt.Sprintf("| context: %s | theme: %s (%s)", m.Context, m.renderer.Theme, render.ThemeConfigSource(m.Theme))))
	fmt.Println(m.renderer.Muted("Type a message, /help, or /quit."))

	scanner := bufio.NewScanner(os.Stdin)
	turnCount := 0
	for {
		if turnCount > 0 {
			fmt.Println()
			fmt.Println(m.renderer.RenderSeparator(72))
		}

		fmt.Print(m.renderer.RenderPrompt())
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
			fmt.Printf("%s %v\n", m.renderer.Error("Error:"), err)
			continue
		}

		if response.ConversationID != nil {
			m.conversationID = response.ConversationID
		}

		fmt.Println()
		fmt.Printf("%s\n\n", m.renderer.RenderAssistantPrefix(response.Agent))
		fmt.Println(m.renderer.RenderMarkdown(response.Result))
		turnCount++
	}
}

func (m *Manager) handleSlashCommand(input string) bool {
	switch input {
	case "/quit", "/exit":
		fmt.Println(m.renderer.Muted("Session closed."))
		os.Exit(0)
	case "/new":
		m.conversationID = nil
		fmt.Println(m.renderer.Warning("New conversation started."))
	case "/id":
		if m.conversationID != nil {
			fmt.Printf("%s %s\n", m.renderer.Muted("conversation:"), *m.conversationID)
		} else {
			fmt.Println(m.renderer.Warning("No active conversation yet."))
		}
	case "/help":
		fmt.Println(m.renderer.Header("Slash commands:"))
		fmt.Println("  /new   - start a new conversation")
		fmt.Println("  /id    - show current conversation ID")
		fmt.Println("  /help  - show this help")
		fmt.Println("  /quit  - close the session")
	default:
		if strings.HasPrefix(input, "/") {
			fmt.Printf("%s %s\n", m.renderer.Error("Unknown command:"), m.renderer.Muted(fmt.Sprintf("%s (type /help)", input)))
			return true
		}
		return false
	}
	return true
}
