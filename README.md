# Ollama Cloud Usage

Adds **Ollama Cloud** to Omarchy's **existing AI toolbar widget** — the AI icon already on the top bar. It does not add a second icon.

After install, click that same AI button. You get an **Ollama Cloud** provider next to Claude Code / Codex: your plan tier, the 5-hour session and weekly limit meters, extra-usage balance, and per-model request counts as recorded from ollama.com.

Preview:

![Ollama Cloud usage panel in Omarchy](preview.png)

## Install

```sh
omarchy plugin add https://github.com/styles01/omarchy-ollama-cloud.git --enable
```

Requires:

- Omarchy with the stock AI widget enabled (`omarchy.agents`, on by default)
- Python 3 on `PATH` (stdlib only)
- A Chromium-based browser (Google Chrome, Chromium, or Brave) **signed in to [ollama.com](https://ollama.com)** — open ollama.com once and make sure you are logged in
- A unlocked desktop keyring session (the browser needs it to decrypt its own cookies)

Leave the built-in AI icon where it is. After the first scan (up to 15 minutes after login, or immediately after a panel refresh), click the AI icon and switch to **Ollama Cloud**.

## Usage

- Left click the existing AI icon: usage panel
- Switch to **Ollama Cloud** with the provider in the panel
- `r` or Enter in the panel: refresh (Ollama Cloud follows the stock update)
- Ollama Cloud also refreshes about every 15 minutes

This plugin is a headless service. It only writes an Ollama Cloud usage record for the stock panel to display.

ollama.com has no usage API, so the collector renders `https://ollama.com/settings` with a **headless copy of your desktop browser profile** and reads the numbers straight off the page: tier name, "Session usage", "Weekly usage" (percent used and reset countdowns), the extra-usage balance, and per-model request segments. Manual override if auto-detection picks the wrong target:

```sh
# pick a specific browser binary
ollama_usage=chromium  # or: OLLAMA_USAGE_BROWSER=chromium
# pick a specific profile directory (e.g. ~/.config/google-chrome/Profile 2)
OLLAMA_USAGE_PROFILE="~/.config/google-chrome/Profile 2"
```

## Remove

```sh
omarchy plugin remove io.github.styles01.ollama-cloud
```

Removal deletes the plugin checkout and drops `~/.local/state/omarchy/agents/usage/ollama.json`, so the Ollama Cloud provider leaves the stock AI panel. It does not change browser profiles, cookies, or sessions.

## Privacy

The collector renders one local page view with your existing browser session. No cookies, tokens, or page content are written anywhere — only the usage numbers land in the state file. Expired sessions are not refreshed; open ollama.com in your browser and sign in again to renew.

## License

MIT. See [LICENSE](LICENSE).