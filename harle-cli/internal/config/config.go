package config

import (
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

const defaultServerURL = "http://127.0.0.1:8000"

type CLIConfig struct {
	ServerURL string `yaml:"server_url"`
	APIToken  string `yaml:"api_token"`
}

func ResolveServerURL(flagValue string, flagChanged bool) string {
	if flagChanged && strings.TrimSpace(flagValue) != "" {
		return strings.TrimSpace(flagValue)
	}
	if envValue := strings.TrimSpace(os.Getenv("HARLE_SERVER_URL")); envValue != "" {
		return envValue
	}

	cfg, err := Load()
	if err == nil {
		if cfgValue := strings.TrimSpace(cfg.ServerURL); cfgValue != "" {
			return cfgValue
		}
	}

	if fallback := strings.TrimSpace(flagValue); fallback != "" {
		return fallback
	}
	return defaultServerURL
}

// ResolveAPIToken returns the bearer token for Harle API requests.
// Precedence: non-empty --token flag, HARLE_API_TOKEN, api_token in cli.yaml, then flag default.
func ResolveAPIToken(flagValue string, flagChanged bool) string {
	if flagChanged && strings.TrimSpace(flagValue) != "" {
		return strings.TrimSpace(flagValue)
	}
	if envValue := strings.TrimSpace(os.Getenv("HARLE_API_TOKEN")); envValue != "" {
		return envValue
	}

	cfg, err := Load()
	if err == nil {
		if cfgValue := strings.TrimSpace(cfg.APIToken); cfgValue != "" {
			return cfgValue
		}
	}

	if fallback := strings.TrimSpace(flagValue); fallback != "" {
		return fallback
	}
	return ""
}

func Load() (CLIConfig, error) {
	path, err := resolvePath()
	if err != nil {
		return CLIConfig{}, err
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return CLIConfig{}, err
	}

	var cfg CLIConfig
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return CLIConfig{}, err
	}
	return cfg, nil
}

func resolvePath() (string, error) {
	if override := strings.TrimSpace(os.Getenv("HARLE_CLI_CONFIG")); override != "" {
		return override, nil
	}
	configHome := strings.TrimSpace(os.Getenv("XDG_CONFIG_HOME"))
	if configHome == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		configHome = filepath.Join(home, ".config")
	}
	return filepath.Join(configHome, "harle", "cli.yaml"), nil
}
