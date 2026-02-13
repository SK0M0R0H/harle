CLI_NAME := harle

.PHONY: build run clean

build:
	go build -o bin/$(CLI_NAME) ./cmd/harle

run:
	go run ./cmd/harle

clean:
	rm -rf bin

