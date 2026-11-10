"""What we sell, run for a client: follow-up messages to the client's own customers.

    wr client new lotus-yoga            make clients-data/lotus-yoga/ with a client.toml to fill in
    wr client preview lotus-yoga        who would get which message today, and the exact words (nothing is sent)
    wr client run lotus-yoga            send today's messages (only once client.toml says approved = true)
    wr client run --all                 every approved client (the robot does this every hour)
    wr client report lotus-yoga         what went out, who answered, who came back, who said stop
    wr client stop lotus-yoga a@b.com   never write to this customer again

A client is a folder in clients-data/ (never uploaded: it holds the client's customer list):

    client.toml      the business, which follow-ups run, the texts' details, approved = true/false
    customers.csv    the client's export: name, email, last_visit, consent, and (optional) unpaid, due
    state.sqlite     what was sent to whom, replies, stops

The four follow-ups (campaigns.py):

    review     a thank-you with the Google review link, 1-7 days after a visit. Everyone is asked the same way,
               nothing is offered in return, nobody is filtered (Google's rules, the FTC's and the CMA's).
    comeback   one reminder when a customer is due again (e.g. six weeks after the last visit)
    winback    up to three friendly notes to customers who have not been in for months
    payment    polite reminders for a missed payment (only customers marked unpaid in the list)

Rules built in: marketing follow-ups go only to customers marked as having agreed (the consent column); every
message says how to stop, and a "stop" is final; never more than one follow-up to a customer at a time; at most
one message a week per customer; a daily limit per client; nothing before the client approved the texts.
"""
