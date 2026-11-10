# Tablet or online server?

WorldReach is the same program in both places, with the same `wr` commands. What differs is where it lives.

| | Your tablet (Termux) | A small online server |
|---|---|---|
| Cost | free | about $5-6 a month |
| Runs 24/7 | only while the tablet has power and Wi-Fi and Android leaves Termux alone; it shares 8 GB with your two other robots | yes, by itself, also after a restart |
| Is it strong enough? | yes | yes. The work is light: 1,500 e-mails a day is a few e-mails a minute. Speed is limited by the mailboxes' warm-up, not by the machine. |
| Finding e-mail addresses | home internet: websites rarely block it | data-centre internet: some websites block it, so somewhat fewer addresses are found (their archived copies are read instead) |
| Sending | from your home internet | from the server's internet. Google and Microsoft may ask you once to confirm a sign-in from a new place. |
| WhatsApp queue | `wr whatsapp` opens the chats | from the Sheet's WhatsApp Queue tab on your phone (a server has no WhatsApp) |
| Setting up | you know it already | one more account (card needed), and you type into the server through Termux |

**My recommendation.** Start on the tablet this week: it costs nothing, it needs no new account, and the first
ten days are small anyway (50-200 e-mails a day per mailbox while they warm up). Move to a server when either
happens: the first client pays, or the tablet misses runs (`wr status` shows them). Moving takes about 20 minutes
and nothing is lost: the memory moves with it.

Do **not** use GitHub Actions for this (GitHub blocked your account's Actions in October for exactly that), and do
not use "free forever" hosts that sleep when idle.

## Setting up a server (when the time comes)

1. **Rent it.** Any provider with a plain Ubuntu server works: Hetzner (CX22, about €4), DigitalOcean (Basic, $6),
   Vultr ($6). Choose **Ubuntu 24.04**, the smallest size with 2 GB memory or more, a location in the US or
   Europe, and a root password (or let it e-mail you one). Note the server's IP address.
2. **Connect from Termux** on the tablet or phone:
   ```
   pkg install -y openssh
   ssh root@YOUR.SERVER.IP
   ```
   Type `yes` at the first question, then the password.
3. **Install** (on the server, one paste):
   ```
   curl -fsSL https://raw.githubusercontent.com/dasravik444-cpu/worldreach/main/server/setup.sh | bash
   ```
4. **Bring your settings, key and memory over.** First, on the tablet, stop the robot: `wr off`. Then, still in
   Termux on the tablet (not inside the server), tell me and I will give you the three exact copy lines for your
   tablet: they copy `settings.txt`, the `secrets` folder and the `data` folder to `/opt/worldreach/` on the server.
   (Starting fresh on the server instead? `wr settings` there, and copy only the Google key file into
   `/opt/worldreach/secrets/`.)
5. On the server: `wr check`, then for each Outlook mailbox `wr outlook-login 4` (the sign-in is per machine),
   then `wr on`.
6. **Only one of the two may run.** Leave the tablet's WorldReach off (`wr off`) once the server is on: two robots
   with the same mailboxes would write to the same businesses twice and break the warm-up.

To come back from the server over SSH later: `ssh root@YOUR.SERVER.IP`, then the usual `wr status`, `wr report`.
