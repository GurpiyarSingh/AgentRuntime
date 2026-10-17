# Agent Runtime Web App: User Guide

This guide explains, in plain language, how to use the Agent Runtime **web
app**: a chat page in your web browser where you ask an AI assistant to work
with your files. You don't need to be a programmer.

![The Agent Runtime web app](docs/screenshot.png)

---

## What is it?

The web app is a friendly front door to the Agent Runtime assistant. Instead
of typing commands into a terminal, you chat with the assistant in your
browser, much like a messaging app.

The assistant can **read** documents (Word, PDF, Excel, PowerPoint, text and
more), **look at** pictures, **create** new files, **edit** text files, and
**search** through your files.

It works inside one folder, called the **workspace**, and cannot see or change
anything outside it. You can choose which folder that is.

> **Two parts work together.** The web app is only the page you look at. The
> real work happens in the **assistant service** (the "backend"), which must be
> running while you use the page. This guide shows you how to start both.

---

## Before you start

You need:

1. **The assistant service, set up once.** Follow the one-time setup in the
   [backend User Guide](../agent-runtime-backend/USER_GUIDE.md#one-time-setup).
   It covers installing Python and adding your OpenAI key. To **save
   conversations and use sign-in**, also follow its optional database step.
2. **Node.js**, which runs the web app. It's free: download the **LTS** version
   from [nodejs.org](https://nodejs.org) and install it with the default
   options.
3. **A web browser**: Chrome, Edge, Firefox or Safari.

> **What's a terminal?** It's a window where you type commands instead of
> clicking. On Windows, open the Start menu and search for **PowerShell**. On a
> Mac, search Spotlight for **Terminal**.

---

## One-time setup

Open a terminal, then type these two lines, pressing **Enter** after each.
Replace the path with wherever the project is on your computer:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-frontend"
npm install
```

This downloads what the web app needs and takes a minute or two. You only do
it once, or again after the web app is updated.

---

## Starting the web app

Each time you want to use it, you start **two things**, each in its own
terminal window.

**Terminal 1: start the assistant service**

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
.\venv\Scripts\Activate.ps1
agent-runtime serve
```

(On Mac/Linux, the middle line is `source venv/bin/activate`.)

**Terminal 2: start the web app**

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-frontend"
npm run dev
```

**Then open your browser** and go to **http://localhost:5173**.

Keep both terminal windows open while you use the app. To finish, close the
browser tab, then press **Ctrl+C** in each terminal (or just close them).

---

## Signing in

![The sign-in page](docs/login.png)

If the assistant service has a database, the app opens on a **sign-in page**.
(Without a database there's no sign-in: the app opens straight away, and the
bottom of the left panel says **Local mode**.)

**The very first time**, the page says **Create your admin account**. You're
the first one here, so you become the administrator:

1. Optionally type your name, as it should appear in the app.
2. Choose a **username**: letters, numbers and `_ . @ -`.
3. Choose a **password** of at least 8 characters. A bar under it shows how
   strong it is; aim for green.
4. Type the password again, and click **Create account & continue**.

**After that**, the page says **Welcome back**. Type your username and
password and click **Sign in**. Usernames ignore upper and lower case. Click the
**eye** to show the password as you type it.

- **Staying signed in.** The app remembers you in this browser for 7 days.
- **Signing out.** Click the **door-and-arrow** button at the bottom of the left
  panel, next to your name.
- **Accounts for other people.** Whoever runs the assistant service creates
  them with `agent-runtime users add NAME` (see the
  [backend guide](../agent-runtime-backend/USER_GUIDE.md#optional-save-conversations-and-add-sign-in)).
  Each person sees only their own conversations.

---

## A tour of the screen

| Area                   | Where            | What it's for                                                                                                        |
| ---------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------- |
| **Status**             | Top left         | A green dot next to **Connected** means the service is running.                                                      |
| **Workspace**          | Left, at the top | The folder the assistant works in. **Browse…** picks another.                                                        |
| **Conversations**      | Left             | Your past conversations, newest first. Shown when the service has a database.                                        |
| **Integrations**       | Left             | Connected services (MCP servers) and their status. **Manage** adds and changes them.                                 |
| **Tools**              | Left             | Everything the assistant can do. Click one for details.                                                              |
| **You**                | Bottom left      | Your name, the **theme** switch (computer, sun, moon), and **sign out**. In Local mode, **Settings** for an API key. |
| **Conversation title** | Top of the chat  | The conversation's name. A **Working** badge appears while the assistant is busy.                                    |
| **Model menu**         | Top right        | Choose which AI model answers (e.g. GPT-4o or GPT-5.2).                                                              |
| **New chat**           | Top right        | Start a fresh conversation.                                                                                          |
| **Message box**        | Bottom           | Where you type. The **paperclip** attaches files, and the **arrow** sends.                                           |

When you start a new conversation, the chat shows four **ideas** to try. Click
one to put it in the message box, change it if you like, and press **Enter**.

---

## Everyday use

### Ask for something

Type in the message box at the bottom and press **Enter**.

- To start a **new line** without sending, press **Shift+Enter**.
- The reply appears **word by word** as it's written.
- The assistant **remembers the conversation**, so you can follow up with
  _"make it shorter"_ or _"now do the same for the other file"_.

Good things to ask:

- _"What files are in my workspace?"_
- _"Summarise the PDF I just attached in five bullet points."_
- _"What does this chart show?"_ (with an image attached)
- _"Which month in budget.xlsx had the highest spending?"_
- _"Create a Word document with a one-page project plan."_
- _"Make a 5-slide presentation about our product launch."_
- _"Make a spreadsheet of monthly expenses: rent 1200, food 400, travel 150."_

### Choose the folder it works in

The **Workspace** box at the top left shows the folder's full path. It says
**default** for the service's own folder, or **chosen** for one you picked.

1. Click **Browse…**. A window opens showing folders on the computer running
   the assistant service.
2. Click a folder to open it, or the **up arrow** to go back up. You can also
   paste a path into the box at the top and press **Enter**.
3. When you're in the right folder, click **Use this folder**.

From then on, the assistant reads and creates files in that folder, and
attachments are uploaded there. Click **Use default** to go back. Your choice
is remembered, and reopening an old conversation switches back to the folder
it used.

> If there's no **Browse…** button, whoever runs the service has switched
> folder choosing off. If some folders are missing, they've limited it to
> certain folders.

### Give the assistant a file

1. Click the **paperclip** next to the message box.
2. Choose one or more files. Each one appears as a small label above the box,
   saying **uploading…** while it's sent.
3. Once the uploads finish, type your request and press **Enter**.

Your files are copied into the workspace's **`uploads`** folder, and the
assistant is told where they are. To take a file back off the message before
sending, click the **×** on its label.

If a label says **already in workspace**, a file with that name was already
there. The existing copy is used and nothing is overwritten. To use a new
version, rename your file first.

### Watch what the assistant does

While it works, a line under the assistant's name says what it's doing, such
as **Thinking…** or **Using read file…**, and its icon gets a spinning ring.

Each step it takes appears as a **card** with a coloured icon for the kind of
step: a folder for listing files, a page for reading, a picture for looking at
images, a magnifier for searching, a green page for creating, a pencil for
editing. For example: **Read file** `uploads/report.pdf` `0.3 s`.

- A **spinning** circle means the step is still running, and a light sweeps
  across the card.
- A green **tick** means it worked.
- A red **warning sign** means it didn't. The assistant usually explains what
  went wrong and tries another way.

Click a card to see exactly what the assistant asked for and what it got back.
You don't need to, but it's there if you're curious.

### Get the files it creates

When the assistant creates a file, that step's card shows a **Download**
button, for example **Download plan.docx**. Click it to save the file to your
computer's Downloads folder.

The file also stays in the workspace folder.

### Stop an answer

While the assistant is working, the arrow button turns into a **square Stop
button**. Click it to cancel.

You'll see _"Stopped. This reply was not saved, so the agent won't remember
it."_ That's expected: a half-finished answer isn't kept, so the next message
starts from a clean point.

### Start over

Click **New chat** (top right) to start a fresh conversation. The previous one
is still in **Conversations** on the left (if the service has a database), and
your files stay in the workspace.

### Choose a model

Use the menu at the top right. **GPT-4o** is fast and inexpensive and right for
most requests. **GPT-5.2** reasons more carefully but is slower. Your choice is
remembered the next time you open the app. The model that wrote each reply is
shown next to the assistant's name.

### See what it cost

Under each finished reply there's a small line such as
`4,722 tokens · $0.0156`. That's how much text the assistant processed and what
that answer cost on your OpenAI account. Most answers cost less than a cent.

---

## Your conversations

If the assistant service has a database, every conversation is saved, and the
**Conversations** list on the left shows them, newest first. Each one shows
when you last used it, how many messages it has, and what it cost.

- **Open one** by clicking it. The whole conversation comes back, including
  every step the assistant took, and you can carry on from where you left off.
  The one you're in is highlighted.
- **Rename** it: point at it and click the **pencil**, type a new name, and
  press **Enter** (or **Esc** to cancel).
- **Delete** it: point at it, click the **bin**, then **Delete** to confirm.
  This removes it permanently, along with its record of everything the
  assistant did.

A new conversation is named after the first line of your first message.

---

## Integrations (MCP servers)

The assistant can use tools from other services too: **GitHub** (issues, pull
requests, code), **Jira** and **Confluence**, a real **web browser**
(Playwright), your **files** elsewhere, and thousands more. Each comes from an
**MCP server**: a small program or online service that offers tools in a
standard way (MCP is the Model Context Protocol).

Connected servers are listed under **Integrations** on the left, each with a
coloured dot:

- **Green**: connected, with how many tools it offers.
- **Amber**: starting. A first start can take a minute while it downloads.
- **Red**: not connected. Open it to see why.
- **Grey**: switched off.

As soon as a server connects, its tools appear in the **Tools** list under the
server's name, and the assistant can use them. In a reply, their steps show as
cards such as **github · create_issue**, with a plug icon.

![Adding an MCP server](docs/mcp.png)

### Add a server

1. Click **Manage** next to **Integrations** (or **Connect an MCP server** if
   there are none yet), then **New server**.
2. **Pick a template**: GitHub, Playwright, Jira & Confluence, Filesystem,
   Fetch or Memory. It fills everything in and tells you what's needed, such as
   a token. Or fill the form in yourself:
   - **Name**: a short name like `github`. The server's tools are named after
     it (`github__create_issue`).
   - **Connection**:
     - **Local command** runs a program on the computer with the assistant
       service, e.g. `npx` with arguments `-y` and
       `@modelcontextprotocol/server-memory`, one per line. Put API keys under
       **Environment variables**.
     - **HTTP** connects to a server on the internet by its address, e.g.
       `https://api.githubcopilot.com/mcp/`. Put your token under **Headers**
       as `Authorization` = `Bearer <your token>`.
     - **SSE** is for older servers whose address usually ends in `/sse`.
3. Replace anything in angle brackets, like `<token>`, with your own details.
4. Click **Test connection**. A green box lists the tools it found; a red one
   says what went wrong, including what the server itself printed.
5. Click **Add server**. It connects straight away.

> Templates that run `npx` need **Node.js** on the computer running the
> assistant service, and those that run `uvx` need **uv**. Servers reached by
> address need neither.

### Import from Claude Desktop, Cursor or VS Code

Already have servers set up in another app? Click **Import**, paste its MCP
configuration (the JSON with `"mcpServers"`), and click **Import servers**.
Servers whose names already exist are skipped unless you tick **Replace
servers that already exist**.

### View, change, pause or remove a server

Click a server to see its status, how it connects, and every tool it offers.

- **Enabled** switch: turn a server off without deleting it, and back on. (The
  switches in the list do the same.)
- **Reconnect**: start a fresh connection, e.g. after the server restarted.
- **Edit**: change anything except the name. Saved secrets show as `••••••••`;
  leave them as they are to keep them, or type a new value.
- **Bin**: delete the server, after a confirmation.

> **Only admins can change servers** when the service has sign-in. Everyone
> else can see them and use their tools.

---

## The tools panel

The left panel lists the assistant's tools, each with its icon. Click one to
see what it does and what information it needs.

The built-in tools are listed first, then each connected MCP server's tools
under its name.

| Tool           | In plain words                                                  |
| -------------- | --------------------------------------------------------------- |
| `list_files`   | Shows what files and folders are in the workspace               |
| `read_file`    | Reads a document: text, PDF, Word, Excel, PowerPoint and more   |
| `read_image`   | Looks at a picture: photos, screenshots, scans, charts          |
| `search_files` | Finds a word or phrase across your text files                   |
| `write_file`   | Creates a new file: Word, PDF, Excel, PowerPoint, text and more |
| `edit_file`    | Changes part of an existing text file                           |

As you chat, a small number appears next to each tool showing how many times
the assistant used it in this conversation (for example **2×**).

If the top of the panel says **read-only**, the assistant can read but not
create or change files, so `write_file` and `edit_file` won't be listed.

---

## Light or dark

The app comes in a dark and a light look. Use the three small buttons at the
bottom left:

- **Computer**: follow your computer's setting (the default)
- **Sun**: always light
- **Moon**: always dark

Your choice is remembered in this browser.

---

## Settings: API key (Local mode only)

Most people can skip this. When the service has no sign-in (**Local mode**),
whoever set it up may have given it a password, called an **API key**. The app
then needs it too:

1. Click **Settings** at the bottom left.
2. Paste the key into the **API key** box and click **Save**.

The panel then shows **API key set**. The key is stored only in this browser on
this computer. To remove it, clear the box and click **Save**.

You'll know you need a key if the tools panel says _"The server needs an API
key."_ With sign-in, there's no API key to enter: your account is enough.

---

## On a phone or small window

On narrow screens the left panel is hidden to make room for the chat. Tap the
**☰ menu** button at the top left to open it, and tap **×** or outside the panel
to close it. The sign-in page shows its picture as a banner above the form.

---

## Privacy and safety

- The assistant **only works inside the workspace folder**. It can't open,
  change or delete anything outside it.
- It **never overwrites an existing file** unless you clearly ask it to.
- Files you attach, and the contents of files it reads, are **sent to OpenAI**
  so the AI can understand them. Don't use it on documents you aren't allowed
  to share with an outside service.
- **With sign-in, your conversations are private to you.** Other people with
  accounts can't see, open or delete them. Your password is stored scrambled
  (hashed), never as written.
- **Saved conversations are kept until you delete them**, in the database of
  whoever runs the service. In Local mode nothing is kept: the assistant
  forgets a conversation after an hour without new messages, or whenever the
  service restarts.
- Your sign-in, theme, model and folder choices are remembered **only in this
  browser**.
- **MCP servers see what the assistant sends them.** Only connect services you
  trust, and give tokens only the access the assistant needs. Saved tokens stay
  on the assistant service and are never shown in the browser again.

---

## Troubleshooting

| You see                                                                          | What to do                                                                                                                                                                                                          |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Can't reach the runtime**, with a **Try again** button                         | Terminal 1 isn't running `agent-runtime serve`. Start it, then click **Try again**.                                                                                                                                 |
| A red **Cannot reach the agent server** banner, or **Offline** in the left panel | The service stopped while you were using the app. Start it again, then click **Retry**.                                                                                                                             |
| The page won't load at all                                                       | Terminal 2 isn't running `npm run dev`. Start it and refresh the page.                                                                                                                                              |
| **Wrong username or password**                                                   | Check the spelling, and that Caps Lock is off. Usernames ignore case, but passwords don't.                                                                                                                          |
| **Too many attempts. Try again in … min.**                                       | Five wrong passwords in a row pause sign-in for that name for a few minutes. Wait, then try again.                                                                                                                  |
| **Your session expired. Sign in again.**                                         | Sign-ins last 7 days. Sign in again; your conversations are still there.                                                                                                                                            |
| I forgot my password                                                             | Ask whoever runs the service to create you a new account with `agent-runtime users add`.                                                                                                                            |
| No sign-in page and no **Conversations**, though a database was set up           | The service reads its settings only when it starts. Restart Terminal 1, then refresh the page.                                                                                                                      |
| `npm` is not recognised                                                          | Node.js isn't installed, or the terminal was opened before installing it. Install Node.js, then open a new terminal.                                                                                                |
| **OPENAI_API_KEY is not set** under a reply                                      | The assistant service has no OpenAI key. Add it to the `.env` file in the `agent-runtime-backend` folder (see the [backend guide](../agent-runtime-backend/USER_GUIDE.md#one-time-setup)), then restart Terminal 1. |
| **Directory not found**, or **outside the directories this server allows**       | The chosen folder was moved, or isn't one you're allowed to use. Click **Browse…** and pick another, or **Use default**.                                                                                            |
| **The server needs an API key**                                                  | Enter the key under **Settings** (bottom left).                                                                                                                                                                     |
| A file label turns red                                                           | That upload failed. The label says why, often that the file is too large. Remove it and try again.                                                                                                                  |
| The model menu says **Loading models…** for a long time                          | The service isn't reachable. See the first row.                                                                                                                                                                     |
| The reply says it **did not finish within 8 steps**                              | The task was too big for one go. Ask for it in smaller pieces.                                                                                                                                                      |
| **The connection closed before the agent finished**                              | The service stopped or restarted mid-answer. Check Terminal 1, then send your message again.                                                                                                                        |
| An MCP server shows **Couldn't start 'npx'** (or `'uvx'`)                        | That helper isn't installed on the computer running the assistant service. Install Node.js (for `npx`) or uv (for `uvx`), then restart the service and click **Reconnect**.                                         |
| An MCP server shows **The server answered HTTP 401**                             | The token is wrong or has expired. Click **Edit**, paste a new token under **Headers**, and save.                                                                                                                   |
| An MCP server shows **didn't answer within … s**                                 | A first start may still be downloading. Click **Edit**, open **Advanced**, raise the start-up timeout, and save.                                                                                                    |
| An MCP server's tools don't appear                                               | Check its dot under **Integrations**: it must be green. A server that's switched off (grey) offers no tools.                                                                                                        |
| An error mentioning OpenAI **quota** or **billing**                              | Add credit or check your limits at [platform.openai.com](https://platform.openai.com/).                                                                                                                             |

Still stuck? The [backend User Guide](../agent-runtime-backend/USER_GUIDE.md#troubleshooting)
covers problems with the assistant service itself.

---

## Quick reference

```text
Start (two terminals):
  1. agent-runtime-backend   ->  .\venv\Scripts\Activate.ps1  then  agent-runtime serve
  2. agent-runtime-frontend  ->  npm run dev
  3. Open http://localhost:5173 and sign in (first visit: create the admin account)

In the app:
  Enter             send              Shift+Enter       new line
  Paperclip         attach files      Square button     stop the answer
  Browse…           choose a folder   New chat          start over
  Conversations     reopen, rename (pencil), delete (bin)
  Card              click to see the step's details
  Download          save a file the assistant created
  Bottom left       theme (computer / sun / moon) and sign out
  Integrations      Manage -> New server (template, Test connection, Add server),
                    Import JSON, switch on/off, Reconnect, Edit, delete
```
