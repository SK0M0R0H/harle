package render

import (
	"fmt"
	"os"
	"strings"
)

type Theme string

const (
	ThemeAuto  Theme = "auto"
	ThemeDark  Theme = "dark"
	ThemeLight Theme = "light"
	ThemePlain Theme = "plain"
)

type Renderer struct {
	Theme Theme
}

func NewRenderer(themeValue string) *Renderer {
	return &Renderer{Theme: resolveTheme(themeValue)}
}

func ThemeConfigSource(themeValue string) string {
	if strings.TrimSpace(themeValue) != "" {
		return "--theme"
	}
	if strings.TrimSpace(os.Getenv("HARLE_DISPLAY_THEME")) != "" {
		return "HARLE_DISPLAY_THEME"
	}
	return "default(auto)"
}

// resolveTheme precedence: --theme flag value, then HARLE_DISPLAY_THEME, then auto.
func resolveTheme(themeValue string) Theme {
	candidate := strings.ToLower(strings.TrimSpace(themeValue))
	if candidate == "" {
		candidate = strings.ToLower(strings.TrimSpace(os.Getenv("HARLE_DISPLAY_THEME")))
	}
	switch Theme(candidate) {
	case ThemeDark, ThemeLight, ThemePlain:
		return Theme(candidate)
	default:
		return ThemeAuto
	}
}

func (r *Renderer) colorize(s, code string) string {
	if r.Theme == ThemePlain {
		return s
	}
	return "\x1b[" + code + "m" + s + "\x1b[0m"
}

func (r *Renderer) Header(text string) string { return r.colorize(text, "1;37") }
func (r *Renderer) Muted(text string) string  { return r.colorize(text, "2") }
func (r *Renderer) Warning(text string) string {
	return r.colorize(text, "1;33")
}
func (r *Renderer) Error(text string) string { return r.colorize(text, "1;31") }

func (r *Renderer) RenderSeparator(width int) string {
	if width < 16 {
		width = 48
	}
	return r.colorize(strings.Repeat("─", width), "90")
}

func (r *Renderer) RenderPrompt() string {
	return r.colorize("harle>", "1;34") + " "
}

func (r *Renderer) RenderAssistantPrefix(agent string) string {
	if strings.TrimSpace(agent) == "" {
		agent = "assistant"
	}
	return r.colorize(fmt.Sprintf("[%s]", agent), "1;35")
}

func (r *Renderer) RenderMarkdown(message string) string {
	trimmed := strings.TrimSpace(message)
	if trimmed == "" {
		return ""
	}

	var out []string
	inCode := false
	for _, line := range strings.Split(trimmed, "\n") {
		plain := strings.TrimSpace(line)
		switch {
		case strings.HasPrefix(plain, "```"):
			inCode = !inCode
			if inCode {
				out = append(out, r.Muted("code:"))
			}
		case inCode:
			out = append(out, r.colorize("  "+line, "36"))
		case strings.HasPrefix(plain, "#"):
			head := strings.TrimSpace(strings.TrimLeft(plain, "#"))
			out = append(out, "")
			out = append(out, r.Header(head))
		case strings.HasPrefix(plain, "- ") || strings.HasPrefix(plain, "* "):
			out = append(out, "  • "+strings.TrimSpace(plain[2:]))
		default:
			out = append(out, line)
		}
	}
	return strings.Join(out, "\n")
}
