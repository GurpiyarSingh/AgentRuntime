# Agent Runtime: User Guide

This guide explains, in plain language, what this program does and how to use
it. You don't need to be a programmer.

---

## What is it?

Agent Runtime is an **AI assistant that can work with your files**. You give
it a folder, and it can:

- **Read** documents: Word, PDF, Excel, PowerPoint, text files, code and more
- **Look at** pictures: photos, screenshots, scanned pages, charts
- **Create** new files: Word documents, PDFs, spreadsheets, slide decks,
  text files and more
- **Search** through your files for a word or phrase
- **Edit** text files

You ask for things in normal English, for example *"Summarise report.pdf into a
one-page Word document"*, and it does the work.

It only ever touches **one folder at a time**, called the **workspace**. It
cannot see or change anything outside that folder. In the web app you can pick
which folder it works in.

There are three ways to use it:

| | Who it's for | What it's like |
|---|---|---|
| **Command line (CLI)** | You, at your computer | You type a request into a terminal window and the answer appears there |
| **Web app** | You, in a browser | A chat page like a messaging app, with the assistant's tools listed on the left |
| **API (web service)** | Other programs and apps | A website or app sends requests to it over the network |

The command line needs the least setup. The web app is the most comfortable
for everyday use.

---

## Before you start

You need three things:

1. **Python 3.11 or newer.** It's free from [python.org/downloads](https://www.python.org/downloads/).
   On Windows, tick **"Add Python to PATH"** during installation.
2. **This project's folder** on your computer.
3. **An OpenAI API key.** This is a password that lets the program use OpenAI's
   AI models. Get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys).
   OpenAI charges a small amount per use (see [What does it cost?](#what-does-it-cost)).

> **What's a terminal?** It's a window where you type commands instead of
> clicking. On Windows, open the Start menu and search for **PowerShell**. On a
> Mac, search Spotlight for **Terminal**.

---

## One-time setup

You only do this once. Open a terminal, then type each line below and press
**Enter** after each one.

**1. Go to the project folder.** This is the **`agent-runtime-backend`**
folder, the one that contains `pyproject.toml` and this guide. Replace the path
with wherever it is on your computer:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
```

> **Always run commands from this folder.** The program looks for its settings
> file (`.env`) in whichever folder you're in. If you run it from somewhere
> else, even the folder just above this one, it won't find your API key.

**2. Create a private Python environment for the program:**

```powershell
python -m venv venv
```

**3. Switch it on.**

On Windows:

```powershell
.\venv\Scripts\Activate.ps1
```

On Mac or Linux:

```bash
source venv/bin/activate
```

You'll see `(venv)` at the start of the line. That means it's on.

> If Windows says *"running scripts is disabled"*, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer **Y**, then try
> again.

**4. Install the program:**

```powershell
pip install -e .
```

This takes a minute or two.

**5. Add your OpenAI key.** Make a copy of the settings file:

```powershell
copy .env.example .env
```

(On Mac/Linux use `cp .env.example .env`.) Open the new **`.env`** file in
Notepad or any text editor and find this line:

```
OPENAI_API_KEY=your-openai-api-key
```

Replace `your-openai-api-key` with your real key, then save the file.

> **Keep your key secret.** Never share the `.env` file or post it online.
> Anyone with your key can spend money on your OpenAI account.

**6. Check it works:**

```powershell
agent-runtime tools
```

You should see a list of tools (`list_files`, `read_file` and so on). Setup is
done.

### Optional: save conversations and add sign-in

On its own, the assistant forgets a conversation after an hour without
messages, or whenever it restarts. If you have **PostgreSQL** (a free database
program, from [postgresql.org](https://www.postgresql.org/download/)), it can
keep every conversation, and a record of everything it did, permanently. The
web app then also asks people to **sign in**, and everyone sees only their own
conversations.

**1. Create an empty database** called `agent_runtime`. In pgAdmin, right-click
**Databases → Create → Database**, or run this in its Query Tool:

```sql
CREATE DATABASE agent_runtime;
```

**2. Tell the assistant where it is.** Add this line to your `.env` file,
with your PostgreSQL user name and password:

```
DATABASE_URL=postgresql://postgres:YOUR-PASSWORD@localhost:5432/agent_runtime
```

The assistant creates its tables the next time it starts.

**3. Create your account.** Start the web app (see [Mode 3](#mode-3-web-app-in-your-browser)).
The first time you open it, it asks you to **create the admin account**:
choose a username and a password of at least 8 characters.

**Adding more people.** Each person needs their own account. Create one from
the terminal; it asks for the new password twice:

```powershell
agent-runtime users add maria
agent-runtime users list            # see everyone, and when they last signed in
```

> **Changed `.env`?** Stop the service (**Ctrl+C**) and start it again. It reads
> its settings only when it starts.

### Optional: connect other tools (MCP servers)

The assistant can also use tools from other services: GitHub, Jira, a real web
browser (Playwright), and thousands more. These come as **MCP servers** (MCP is
the Model Context Protocol, a common way for AI assistants to plug into tools).

The easiest way to add one is in the web app: click **Manage** next to
**Integrations** on the left, pick a template, fill in your token, and click
**Test connection**. The
[Web App User Guide](../agent-runtime-frontend/USER_GUIDE.md#integrations-mcp-servers)
walks through it.

Many servers are started with one of two helper programs, which must be
installed on the computer running the assistant service:

- **`npx`** comes with [Node.js](https://nodejs.org) (Playwright, GitHub
  tools, files, memory).
- **`uvx`** comes with [uv](https://docs.astral.sh/uv/getting-started/installation/)
  (Jira and Confluence, web page fetching).

Servers on the internet (like GitHub's) need neither: they're reached by
address. Connected servers work in the command line too: `chat` and `ask`
connect them automatically and show `[mcp] github: 41 tools`. Add
`--no-mcp` to skip them.

---

## Every time you use it

Open a terminal, go to the project folder, and switch the environment on:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
.\venv\Scripts\Activate.ps1
```

Then use either of the two modes below.

---

## Mode 1: Command line

### Where do my files go?

The assistant works inside the **workspace folder**. By default that's
`data\workspace` inside the project folder, and it's created automatically the
first time you run the program.

- **To give it a file**, copy the file into that folder.
- **Files it creates** appear in that same folder.

To use a different folder, add `--workspace` and the folder's path to any
command:

```powershell
agent-runtime chat --workspace "C:\Users\me\Documents\Reports"
```

### Have a conversation

```powershell
agent-runtime chat
```

Type your request after `you>` and press **Enter**. The assistant remembers
what you said earlier in the conversation, so you can follow up with things like
*"now make it shorter"*.

While it works, you'll see lines like these:

```
you> What's in report.pdf?
  [tool] read_file(path='report.pdf')
  [ok 0.3s] File: report.pdf (pdf, 84.2 KB)
The report covers third-quarter sales. Revenue rose 12%...
  [2 steps, 4722 tokens, $0.0156]
```

- Lines starting with `[tool]` show what the assistant is doing.
- `[ok ...]` means that step worked. `[failed]` means it didn't, and the
  assistant will explain why.
- The last line shows how much that answer cost.

**Commands you can type in a conversation:**

| Type this | What happens |
|---|---|
| `/new` | Start a fresh conversation (it forgets the earlier messages) |
| `/help` | Show these commands |
| `/exit` | Quit. Pressing **Ctrl+C** also works |

To stop an answer that's taking too long, press **Ctrl+C** once. You'll stay in
the conversation.

### Ask a single question

If you just want one answer, use `ask`:

```powershell
agent-runtime ask "List the files in my workspace"
```

It prints the answer and finishes.

### Things you can ask for

- *"What files do I have?"*
- *"Summarise contract.pdf in five bullet points."*
- *"What does the chart in sales.png show?"*
- *"Read budget.xlsx and tell me which month had the highest spending."*
- *"Turn notes.txt into a nicely formatted Word document called notes.docx."*
- *"Make a 5-slide presentation about our product launch, saved as launch.pptx."*
- *"Create a spreadsheet of these expenses: rent 1200, food 400, travel 150."*
- *"Find every file that mentions 'invoice'."*
- *"In config.txt, change 'debug=true' to 'debug=false'."*

### Useful options

Add these after `chat` or `ask`:

| Option | What it does |
|---|---|
| `--workspace "FOLDER"` | Use a different folder |
| `--read-only` | Let it read files but never create or change any. A safe way to explore. |
| `--model gpt-5.2` | Use the stronger (slower) model. Run `agent-runtime models` to see choices. |
| `-q` | Quiet: show only the answer, without the activity lines |
| `--no-stream` | Show the answer all at once at the end, instead of word by word |

---

## Mode 2: API (for apps and developers)

This mode turns the program into a **web service**, so websites, apps or
scripts can use the assistant without a person typing into a terminal.

**Start the service:**

```powershell
agent-runtime serve
```

Leave that window open; the service runs until you close it or press
**Ctrl+C**.

**Try it in your web browser:** open
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). You'll get an
interactive page where you can try every feature:

1. Click **POST /v1/files**, then **Try it out**, choose a file, and click
   **Execute** to upload it to the workspace.
2. Click **POST /v1/chat**, then **Try it out**, and type your request in the
   `message` box, for example `"Summarise the file I just uploaded"`. Click
   **Execute**, and the answer appears below.
3. Click **GET /v1/files/{file_path}** to download any file the assistant
   created.

Developers will find the full technical details in [README.md](README.md).

> **Sharing the service with other computers?** By default it only accepts
> connections from your own computer, which is safe. Before letting other
> machines connect, set an `API_KEY` password in the `.env` file. Otherwise
> anyone who can reach it can read and delete your workspace files.

---

## Mode 3: Web app (in your browser)

The web app is a chat page in your browser. The tools the assistant can use
are listed on the left, and the conversation is on the right.

**One-time setup.** You need **Node.js** (free from
[nodejs.org](https://nodejs.org), the "LTS" version). Then open a terminal in
the **`agent-runtime-frontend`** folder, which sits next to this one, and run:

```powershell
npm install
```

**Every time.** The web app needs the assistant's service running behind it,
so use **two terminal windows**:

1. In the first, start the service from the `agent-runtime-backend` folder:

   ```powershell
   cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
   .\venv\Scripts\Activate.ps1
   agent-runtime serve
   ```

2. In the second, start the web app from the `agent-runtime-frontend` folder:

   ```powershell
   cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-frontend"
   npm run dev
   ```

3. Open [http://localhost:5173](http://localhost:5173) in your browser.

If you set up a database, you'll see a **sign-in page** first. On the very
first visit it asks you to create the admin account.

In the web app you can also **choose which folder the assistant works in**:
click **Browse…** in the **Workspace** box on the left and pick any folder.

The **[Web App User Guide](../agent-runtime-frontend/USER_GUIDE.md)** explains
everything on the page step by step: signing in, choosing a folder, attaching
files, following what the assistant does, downloading what it creates,
reopening past conversations, and fixing common problems.

---

## What does it cost?

The program itself is free. OpenAI charges for the AI model each time the
assistant thinks. The cost depends on how much text and how many images it
processes:

- A quick question usually costs **less than one US cent**.
- Reading a long document or several images costs a few cents.
- After each answer, the command line shows the cost, e.g. `$0.0156`.

You can set a monthly spending limit on your OpenAI account at
[platform.openai.com](https://platform.openai.com/).

---

## Is it safe?

- It **only works inside the workspace folder** you give it. It cannot open,
  change or delete anything outside that folder.
- It **never overwrites an existing file** unless you clearly ask it to.
- With `--read-only` it **cannot change anything at all**.
- The command line has **no way to delete files**.
- **The web app's folder picker can open any folder the service can read.**
  That's what you want on your own computer. If other people can reach the
  service, limit it to the folders you mean to share, by adding a line like
  `WORKSPACE_BROWSE_ROOTS=D:\Shared` to `.env`.
- **With a database, everyone signs in** and sees only their own
  conversations. Passwords are stored scrambled (hashed), never as written.
- **An MCP server is a program or service you choose to trust.** A local one
  runs on the computer with the assistant service; a remote one receives what
  the assistant sends it. Only add servers you trust, and give tokens only the
  permissions the assistant needs. With sign-in, only admins can add them.
- Your files are sent to OpenAI so the AI can read them. Don't use it on
  documents you're not allowed to share with an outside service.

---

## Troubleshooting

| You see | What to do |
|---|---|
| `agent-runtime` is not recognised | Switch the environment on first (`.\venv\Scripts\Activate.ps1`), or redo setup step 4. |
| It worked before, but broke after the folder was moved or renamed | The private environment remembers the old location. Switch it on and run `pip install -e .` again from the new folder. |
| `OPENAI_API_KEY is not set` | Check that the `.env` file exists in the `agent-runtime-backend` folder and contains your key (setup step 5), and that your terminal is in that folder (`cd` to it first). |
| `running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and answer **Y**. |
| `File not found: report.pdf` | Copy the file into the workspace folder (`data\workspace`) first, and check the spelling. |
| `... is outside the workspace` | It can only use files inside the workspace folder. Move the file there. |
| `... already exists` | Ask it to replace the file, or choose a different name. |
| `legacy binary format` | Old `.doc`, `.xls` or `.ppt` files can't be read. Open them in Office and *Save As* `.docx`, `.xlsx` or `.pptx`. |
| A scanned PDF gives no text | Scans are pictures, not text. Save the page as an image and ask the assistant to look at it. |
| `did not finish within 8 steps` | The task was too big for one go. Break it into smaller requests, or add `--max-steps 15`. |
| An error from OpenAI about quota or billing | Add credit or check your limits at [platform.openai.com](https://platform.openai.com/). |
| The service won't start and mentions the database, `password authentication failed` or `connection refused` | Check that PostgreSQL is running, and that the user name, password and database name in `DATABASE_URL` are right. |
| `database "agent_runtime" does not exist` | Create it first (see [Optional: save conversations](#optional-save-conversations-and-add-sign-in)). |
| The web app doesn't show a sign-in page, or **Conversations**, after adding `DATABASE_URL` | The service only reads `.env` when it starts. Stop it with **Ctrl+C** and start it again. |
| `accounts need a database` from `agent-runtime users` | Add `DATABASE_URL` to `.env` first. |
| `The username ... is taken` | Pick another name. Usernames ignore upper and lower case. |
| An MCP server says `Couldn't start 'npx'` (or `'uvx'`): not found | Install Node.js (for `npx`) or uv (for `uvx`), open a new terminal, and restart the service. |
| An MCP server says `The server answered HTTP 401` | The token in its headers is wrong or expired. Edit the server and paste a new one. |
| An MCP server says `didn't answer within 60s` | A first start may still be downloading. Edit the server, open **Advanced**, and raise the timeout. |

---

## Quick reference

```text
agent-runtime chat                      Start a conversation
agent-runtime ask "your question"       Ask one thing and get the answer
agent-runtime serve                     Start the web service (API)
agent-runtime tools                     See what the assistant can do
agent-runtime models                    See which AI models you can choose
agent-runtime users add NAME            Create a web app account (needs a database)
agent-runtime users list                See every account
agent-runtime chat --no-mcp             Chat without connecting MCP servers
agent-runtime --help                    Show all commands
agent-runtime chat --help               Show all options for a command

npm run dev        (in agent-runtime-frontend, with "serve" running)
                   Start the web app at http://localhost:5173
```
