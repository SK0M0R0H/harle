package main

import (
	"log"

	"github.com/skm/harle/harle-cli/internal/commands"
)

func main() {
	if err := commands.NewRootCommand().Execute(); err != nil {
		log.Fatal(err)
	}
}
