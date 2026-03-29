package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/skm/harle/harle-cli/internal/commands"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := commands.NewRootCommand().ExecuteContext(ctx); err != nil {
		log.Fatal(err)
	}
}
