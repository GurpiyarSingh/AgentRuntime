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

It works inside one folder on your computer, called the **workspace**, and
cannot see or change anything outside it.

> **Two parts work together.** The web app is only the page you look at. The
> real work happens in the **assistant service** (the "backend"), which must be
> running while you use the page. This guide shows you how to start both.

---

## Before you start

You need:

1. **The assistant service, set up once.** Follow the one-time setup in the
   [backend User Guide](../agent-runtime-backend/USER_GUIDE.md#one-time-setup).
   It covers installing Python and adding your OpenAI key.
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

## A tour of the screen

| Area            | Where       | What it's for                                                                                          |
| --------------- | ----------- | ------------------------------------------------------------------------------------------------------ |
| **Tools panel** | Left side   | Lists everything the assistant can do. A green dot next to **Connected** means the service is running. |
| **Chat**        | Middle      | Your conversation with the assistant.                                                                  |
| **Message box** | Bottom      | Where you type. The **paperclip** attaches files, and the **arrow** sends.                             |
| **Model menu**  | Top right   | Choose which AI model answers (e.g. GPT-4o or GPT-5.2).                                                |
| **New chat**    | Top right   | Start a fresh conversation.                                                                            |
| **Settings**    | Bottom left | Enter an API key, if your service needs one.                                                           |

When you first open the page, the chat shows a few **example requests**. Click
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

While it works, each step appears as a small **card** in the reply, for
example `read_file  uploads/report.pdf  0.3 s`:

- A **spinning** circle means the step is still running.
- A **tick** means it worked.
- A **warning sign** means it didn't. The assistant usually explains what went
  wrong and tries another way.

Click a card to see exactly what the assistant asked for and what it got back.
You don't need to, but it's there if you're curious.

While it's thinking between steps, you'll see three bouncing dots.

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

Click **New chat** (top right) to clear the conversation and start fresh. The
assistant forgets the previous conversation, but your files stay in the
workspace.

### Choose a model

Use the menu at the top right. **GPT-4o** is fast and inexpensive and right for
most requests. **GPT-5.2** reasons more carefully but is slower. Your choice is
remembered the next time you open the app.

### See what it cost

Under each finished reply there's a small line such as
`gpt-4o · 4,722 tokens · $0.0156`. That's the model used, how much text it
processed, and what that answer cost on your OpenAI account. Most answers cost
less than a cent.

---

## The tools panel

The left panel lists the assistant's tools. Click one to see what it does and
what information it needs.

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

If the panel says **read-only** at the top, the assistant can read but not
create or change files, so `write_file` and `edit_file` won't be listed.

---

## Settings: API key

Most people can skip this. If whoever set up the assistant service gave it a
password (an **API key**), the app needs it too:

1. Click **Settings** at the bottom left.
2. Paste the key into the **API key** box and click **Save**.

The panel then shows **API key set**. The key is stored only in this browser on
this computer. To remove it, clear the box and click **Save**.

You'll know you need a key if the tools panel says _"The server needs an API
key."_

---

## On a phone or small window

On narrow screens the tools panel is hidden to make room for the chat. Tap the
**☰ menu** button at the top left to open it, and tap **×** or outside the panel
to close it.

---

## Privacy and safety

- The assistant **only works inside the workspace folder**. It can't open,
  change or delete anything else on your computer.
- It **never overwrites an existing file** unless you clearly ask it to.
- Files you attach, and the contents of files it reads, are **sent to OpenAI**
  so the AI can understand them. Don't use it on documents you aren't allowed
  to share with an outside service.
- Your API key (if any) and model choice are saved **only in your browser**.
- Conversations are not saved permanently. The assistant forgets one after an
  hour without new messages, or whenever the assistant service is restarted.
  Refreshing the page also clears the conversation from the screen.

---

## Troubleshooting

| You see                                                                           | What to do                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A red **Cannot reach the agent server** banner, or **Offline** in the tools panel | Terminal 1 isn't running `agent-runtime serve`. Start it, then click **Retry**.                                                                                                                                     |
| The page won't load at all                                                        | Terminal 2 isn't running `npm run dev`. Start it and refresh the page.                                                                                                                                              |
| `npm` is not recognised                                                           | Node.js isn't installed, or the terminal was opened before installing it. Install Node.js, then open a new terminal.                                                                                                |
| **OPENAI_API_KEY is not set** under a reply                                       | The assistant service has no OpenAI key. Add it to the `.env` file in the `agent-runtime-backend` folder (see the [backend guide](../agent-runtime-backend/USER_GUIDE.md#one-time-setup)), then restart Terminal 1. |
| **The server needs an API key**                                                   | Enter the key under **Settings** (bottom left).                                                                                                                                                                     |
| A file label turns red                                                            | That upload failed. The label says why, often that the file is too large. Remove it and try again.                                                                                                                  |
| The model menu says **Loading models…** for a long time                           | The service isn't reachable. See the first row.                                                                                                                                                                     |
| The reply says it **did not finish within 8 steps**                               | The task was too big for one go. Ask for it in smaller pieces.                                                                                                                                                      |
| **The connection closed before the agent finished**                               | The service stopped or restarted mid-answer. Check Terminal 1, then send your message again.                                                                                                                        |
| An error mentioning OpenAI **quota** or **billing**                               | Add credit or check your limits at [platform.openai.com](https://platform.openai.com/).                                                                                                                             |

Still stuck? The [backend User Guide](../agent-runtime-backend/USER_GUIDE.md#troubleshooting)
covers problems with the assistant service itself.

---

## Quick reference

```text
Start (two terminals):
  1. agent-runtime-backend   ->  .\venv\Scripts\Activate.ps1  then  agent-runtime serve
  2. agent-runtime-frontend  ->  npm run dev
  3. Open http://localhost:5173

In the app:
  Enter             send            Shift+Enter    new line
  Paperclip         attach files    Square button  stop the answer
  New chat          start over      Card           click to see the step's details
  Download          save a file the assistant created
```
