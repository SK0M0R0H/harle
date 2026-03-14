package commands

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/spf13/cobra"
)

func newInterviewCommand(serverURL *string) *cobra.Command {
	var (
		scope  string
		tiers  []int
		resume bool
	)

	command := &cobra.Command{
		Use:   "interview",
		Short: "Start (or resume) a conversational interview",
		Long: `Run a multi-turn conversational interview where Harle asks
structured questions, adapts follow-ups from your answers, and
produces vault Markdown documents.

The interview is pauseable and resumable. Use --resume to continue
a previously paused session.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(*serverURL)
			return runInterview(context.Background(), httpClient, scope, tiers, resume)
		},
	}

	command.Flags().StringVar(&scope, "scope", "all", "Topic scope: all, work, personal, goals")
	command.Flags().IntSliceVar(&tiers, "tier", []int{1, 2}, "Target tiers (1-4, can specify multiple)")
	command.Flags().BoolVar(&resume, "resume", false, "Resume a paused interview session")

	return command
}

func runInterview(ctx context.Context, httpClient *client.HTTPClient, scope string, tiers []int, resume bool) error {
	fmt.Println("Harle Interview")
	fmt.Println("════════════════")
	if resume {
		fmt.Println("Resuming previous session...")
	} else {
		fmt.Printf("Scope: %s | Tiers: %v\n", scope, tiers)
	}
	fmt.Println("Type your answers, or use: /pause, /skip, /quit")
	fmt.Println()

	resp, err := httpClient.InterviewStart(ctx, client.InterviewStartRequest{
		Scope:  scope,
		Tiers:  tiers,
		Resume: resume,
	})
	if err != nil {
		return fmt.Errorf("failed to start interview: %w", err)
	}

	scanner := bufio.NewScanner(os.Stdin)
	runID := resp.RunID

	for {
		printInterviewResponse(resp)

		if resp.Action == "complete" || resp.Action == "paused" || resp.Action == "error" {
			return nil
		}

		fmt.Print("\n> ")
		if !scanner.Scan() {
			fmt.Println()
			resp, _ = httpClient.InterviewRespond(ctx, client.InterviewRespondRequest{
				RunID: runID, Action: "pause",
			})
			printInterviewResponse(resp)
			return nil
		}

		input := strings.TrimSpace(scanner.Text())
		if input == "" {
			continue
		}

		action, userText := parseInterviewInput(input, resp.Action)
		if action == "quit" {
			resp, _ = httpClient.InterviewRespond(ctx, client.InterviewRespondRequest{
				RunID: runID, Action: "pause",
			})
			printInterviewResponse(resp)
			return nil
		}

		resp, err = httpClient.InterviewRespond(ctx, client.InterviewRespondRequest{
			RunID:    runID,
			Response: userText,
			Action:   action,
		})
		if err != nil {
			fmt.Printf("Error: %v\n", err)
			continue
		}
	}
}

func parseInterviewInput(input string, currentAction string) (action, text string) {
	switch strings.ToLower(input) {
	case "/pause":
		return "pause", ""
	case "/skip":
		return "skip", ""
	case "/quit", "/exit":
		return "quit", ""
	case "/continue", "y", "yes":
		if currentAction == "tier_break" {
			return "continue", ""
		}
		if currentAction == "draft" || currentAction == "summary" {
			return "approve", ""
		}
		return "answer", input
	case "n", "no":
		if currentAction == "tier_break" {
			return "stop", ""
		}
		return "answer", input
	default:
		if currentAction == "draft" || currentAction == "summary" {
			return "edit", input
		}
		return "answer", input
	}
}

func printInterviewResponse(resp client.InterviewResponse) {
	switch resp.Action {
	case "question":
		if resp.TopicName != nil {
			fmt.Printf("[%s]\n", *resp.TopicName)
		}
		fmt.Println(resp.Message)

	case "draft":
		fmt.Println(resp.Message)
		if resp.DraftContent != nil {
			fmt.Println()
			fmt.Println("─── Draft ───────────────────────────────")
			fmt.Println(*resp.DraftContent)
			fmt.Println("──────────────────────────────────────────")
		}
		fmt.Println("\nApprove (y), add corrections (type what to add/change — I'll integrate it), or skip (/skip)?")

	case "summary":
		fmt.Println(resp.Message)

	case "tier_break":
		fmt.Println(resp.Message)
		fmt.Println("\nContinue (y) or stop for today (n)?")

	case "complete":
		fmt.Println()
		fmt.Println("════════════════════════════════════════")
		fmt.Println(resp.Message)
		fmt.Printf("Progress: %d/%d topics completed", resp.Progress.Completed, resp.Progress.Total)
		if resp.Progress.Skipped > 0 {
			fmt.Printf(", %d skipped", resp.Progress.Skipped)
		}
		fmt.Println()
		fmt.Println("════════════════════════════════════════")

	case "paused":
		fmt.Println()
		fmt.Println(resp.Message)

	case "error":
		fmt.Printf("Error: %s\n", resp.Message)

	default:
		fmt.Println(resp.Message)
	}
}
