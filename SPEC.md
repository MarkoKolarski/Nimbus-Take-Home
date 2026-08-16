Take-Home Assignment — Document Intelligence 
Platform 
⏱ Timebox: 8 hours 
Eight hours of actual work. Not eight hours spread over a week until it's finished — stop at eight 
and submit what you have. 
This brief describes more than fits in eight hours. That is intentional. Deciding what to 
build, what to cut, and why is the part we are actually assessing. A small system that works, with 
a clear explanation of what was left out, beats a large half-finished one every time. 
The idea 
A platform where a user connects their own external storage, picks a directory, syncs it into a 
knowledge base, and then chats with an LLM over the content of those documents. 
"Chat with a PDF" is the easy part. The substance is everything around it: different storage 
providers, keeping a directory in sync, not repeating work you've already done, and making sure 
one user can never see another user's documents. 
Step 1 — Send us your plan (before you write code) 
Short, informal, half a page. Email or message it, then start. 
1. What you will build in the eight hours. 
2. What you are cutting, and why. 
3. For the top two or three things you kept: what makes them worth the time — what do 
they demonstrate or unlock that the alternatives don't? 
4. Anything in the brief you find ambiguous. 
We reply quickly. If something in your plan looks like a trap, we'll say so — this is a 
conversation, not a test of mind-reading. Also tell us when you're about to start the part that 
needs an LLM, so we can top up the OpenRouter account with credits. 
We read this plan alongside the code. Strong reasoning here can carry a thin implementation; a 
large implementation with no reasoning behind it can't carry itself. 
The full picture 
Everything below is in scope as a wish list. Nobody delivers all of it in eight hours. 
Authentication — Sign in with Clerk, or with a regular email/password screen backed by Ory 
Kratos. Both should produce the same kind of user inside your system. 
Datasources — Connect external storage: S3, Google Drive, Azure Blob. Each provider needs 
different setup information from the user (S3 needs credentials and a bucket; Drive needs an 
OAuth grant), so the instructions and the form differ per provider. 
Directories — Browse a connected datasource, register one or more directories to track, 
manage them afterwards. 
Sync — A Sync button per directory that reports honestly: nothing new to sync / already in 
progress / running with some progress / finished with a summary. Synced files get extracted, 
chunked, embedded into a vector store, and recorded in Postgres. 
Deduplication — The same file must not be processed and inserted into the vector store twice 
— not on a re-sync, not when it appears in a second directory. 
Isolation — Users share no knowledge. There must be no path by which one user's question 
retrieves another user's document. 
Removal — A user can remove a file from their knowledge base, and it stops affecting answers. 
Chat — A chat panel on the right. Questions get answers grounded in that user's own indexed 
documents. 
Extras — Multiple separate chats; a chat that remembers earlier turns; context compaction for 
long conversations; citations back to the source file. 
The one thing that must actually run 
Whatever else you cut, we want to see a working path from connect something → sync it → ask 
a question → get an answer from those documents. 
One storage provider is enough. One auth method is enough. A local S3 emulator instead of a 
real AWS account is enough. Two hardcoded users are enough to demonstrate isolation. Depth 
on this one path is worth more than breadth across the wish list. 
Where to pay attention 
Dedup and isolation pull against each other. "Don't embed the same file twice" wants shared 
storage; "users share no knowledge" wants strict separation. Resolving that is the most 
interesting decision here. Even if you only get as far as writing down how you'd do it, write it 
down. 
Define what "the same file" means. Same path? Same name? Same bytes? Same text after 
extraction? Your answer decides what a second sync of an unchanged directory costs you — 
ideally close to nothing, since extraction and embedding both cost real money and time. 
Sync is a state machine, not a button. Two clicks in a row, a page refresh mid-run, a file 
deleted at the source, a worker that dies halfway. Decide what happens in each case. A small 
honest state machine beats an optimistic one. 
Service boundaries should have a reason. You're free to split things however you like; we'll 
ask why you split them that way. 
Be explicit about what you skipped. Cutting scope is expected. Silently leaving something 
broken is not. 
Tech 
Free choice, with two constraints: it must be a monorepo, and it must run from a clean clone 
with one command (docker compose up or a documented equivalent). 
What we had in mind — not a requirement — is Next.js/React on the frontend, Go and/or 
Python (FastAPI) for services, LangChain or LangGraph for the RAG pipeline, Pinecone for 
vectors, Postgres (NeonDB) for metadata, LocalStack for local S3 and queues. Use 
OpenRouter for LLM calls. 
If you're faster somewhere else, use that and say why in the README. 
Deliverables 
1. The plan from Step 1 (sent before you start). 
2. Source code in one repository, committed as you go rather than in a single drop. 
3. README — setup, environment variables, how to run it from a clean clone. 
4. A diagram — architecture, data flow, sync lifecycle, whatever helps most. A photo of a 
whiteboard is fine. 
5. A short write-up, one page maximum: - 
what you built and what you cut, and whether the plan survived contact with the 
code - - - 
how you handled (or would handle) deduplication 
how you keep users' documents separate 
what you'd do next with another eight hours 
6. A 5–10 minute walkthrough, live or recorded. 
How we evaluate 
What 
Scoping 
Correctness 
What we look for 
Sensible cuts, with reasons — and 
awareness of what each choice buys or costs 
The core path works end to end from a clean 
clone 
Design judgement 
Data safety 
Code quality 
Communication 
Trade-offs named deliberately, not stumbled 
into 
Isolation holds when we try to break it 
Readable and consistent — not exhaustive 
Plan, README, and walkthrough explain the 
thinking 
UI polish is not scored. It should be usable, not beautiful. 
Practical notes - - - 
Ask questions at any point. Clarifying an ambiguous requirement counts in your favour. 
We provide or fund any credentials you need — Pinecone, OpenRouter, Clerk, Neon. 
Just ask. 
If you hit the eight hours mid-feature, stop and write it up. That's a normal outcome, not a 
failure.