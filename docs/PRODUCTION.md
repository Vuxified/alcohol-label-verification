# Taking it to production at TTB

The short version is in the [README](../README.md#production-at-ttb). This page has the reasoning behind each step.

I built this prototype from the outside, without access to TTB's systems or data. Here is what I would change with that access.

**Why I used AWS for the prototype.** I treat a prototype as a way to find out quickly and cheaply whether an idea works before anyone invests in it. AWS was the fastest way for me to put a working app in front of reviewers: $0 while idle, about $0.0005 per label, deployed in minutes. It is not where I would run this in production. The app is one container that runs anywhere Docker does, so I would run the production version in the cloud the agency already uses and has approved (for example Azure Government or AWS GovCloud, both FedRAMP High), or on agency servers.

**Reading everything automatically, including the brand.** Today, with pictures only and nothing typed, the app fills in every box itself except the brand: the product type, class, alcohol, net contents, bottler and the full warning, all read inside the container with no internet. The brand is the hard one. Reading the words is not the problem; telling which of the label's words is the brand ("OLD LANTERN" and not "Small Batch" or "Since 1892") takes understanding of the whole label. So I also had the app send the pictures to an AI vision model (Amazon Nova Pro). I added that as an extra on top. Behind an agency firewall it switches off and the brand says Please check; everything else works the same. Inside TTB, I would have the brand read automatically in one of these ways:
1. **The same AI step inside the agency's approved cloud.** Then it is no longer outside the firewall, and nothing else changes.
2. **An open-weight vision model running on agency servers,** so no picture leaves the agency.
3. **TTB's own label database as a brand list.** TTB holds every brand it has ever approved, and the applicant's own past approvals. A brand already on file is recognized at once, and a new brand falls back to 1 or 2. (From outside, the only route to that data is the public registry website, which can't be copied politely, so I didn't do this.)
4. **No typing at all:** pulling the application values straight from COLA, so the agent never types them (out of scope for this brief).

In every case the agent still confirms. The AI fills in boxes; it never decides a verdict.

**Better test data.** I tested the prototype on 227 real approved labels from the public registry, the same labels with one planted change each, and 96 generated labels with known mistakes. Inside TTB, I would:
- Use the full history of approved *and rejected* applications as truth data, with the reason for each rejection.
- Generate many more realistic labels with planted mistakes, have agents check that they look right, and label them.
- Keep a final-test set apart that no one tunes against, as I did here.

**Learning from past decisions.** I would connect the app to a searchable library of TTB's past work: similar labels already approved or rejected, and why; the warning wordings and layouts that are commonly seen; TTB rulings and guidance. With each result, the agent would see "labels like this were handled like this", with links. This is reference material for the agent, never an automatic decision.

**Getting better over time.** I would turn every "I disagree" note into a lesson:
1. A reviewer sorts the notes.
2. Each real miss becomes a rule fix with a test, or new examples for the next reader training.
3. An improvement agent could draft those fixes automatically from the notes.
4. A person approves each fix, and nothing ships unless it passes the same safety gate as today: 0 wrong answers on every practice set.

**Running at TTB's scale.** TTB reviews about 150,000 applications a year with 47 agents, and importers send 200–300 at once in peak season. The computing is cheap: 150,000 checks at about $0.0005 each comes to about $75 a year. The design is what has to change. These are the changes I would make, drawing on how enterprise document-processing systems are built and on federal AI guidance:
1. **Check each application when it arrives, not when an agent opens it.** The result is stored with the application ID and the version submitted, so the agent opens a finished check. A peak-season dump waits in a queue instead of slowing anyone down, and the 5-second limit only matters for re-checks. The checking code (`app/pipeline.py`) already takes an application in and gives a result out, so it moves behind a queue as is.
2. **Batches that run on the server.** Today a batch runs from the agent's browser tab and stops if the tab closes. In production a batch is a job: a queue (Azure Service Bus or Amazon SQS) feeding copies of the same container, a progress page, and results kept until exported. This is the pattern Amazon publishes for document processing with human review ([AWS](https://aws.amazon.com/blogs/machine-learning/processing-pdf-documents-with-a-human-loop-using-amazon-textract-and-amazon-augmented-ai)). Single checks and batches get separate capacity, so one importer's 300 labels never make an agent wait.
3. **Never read the same picture twice.** Importers reuse artwork: the same back label on hundreds of products, and resubmissions that change one line. I would store each picture's reading under a fingerprint of its file. A repeat costs only the rules, a few milliseconds. A shared back label is reported once ("this warning is confirmed for 212 labels"). For a resubmission, the agent sees only the words that changed since the last version; the app already highlights differing words.
4. **A quiet trial before anyone relies on it.** For a few weeks the app checks every real application without showing agents, and its answers are compared with the agents' decisions. Every "Matches" on an application an agent rejected counts as a wrong answer, measured on TTB's real labels rather than mine. Federal guidance for high-impact AI asks for exactly this: testing in real-world conditions, an impact assessment and ongoing monitoring, even when a person makes the final decision ([OMB M-25-21](https://www.whitehouse.gov/wp-content/uploads/2025/02/M-25-21-Accelerating-Federal-Use-of-AI-through-Innovation-Governance-and-Public-Trust.pdf)). It is the same scoring my safety gate already uses.
5. **A weekly health check without storing labels.** I would log only each answer's code, the version and the time, never the pictures or the text, and chart how often each item says Please check or Does not match. A sudden jump means something changed (a new can format, a reader problem) and shows up before agents notice. This is the "measure" part of the [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework).
6. **Set the bar per item, from TTB's own data.** Today an uncertain reading goes to the agent when the two readers disagree. With real volumes, I would set the cut-off separately for each item and product type, choosing it on agent-checked applications so that a stated share of real errors is always caught. I would set it again whenever the reader changes. Enterprise document tools set their review cut-offs per field in this way ([Amazon A2I](https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-get-started-console.html)).
7. **A third reader inside the agency's cloud.** A word-for-word text service in the approved cloud (Azure AI Document Intelligence has an Azure Government version) would act as one more confirming reader. It would settle more of the items that now say Please check (about a quarter), and still no AI would decide a verdict. Switched off, the app behaves as it does today.
8. **Let applicants check before they submit.** The same check, offered in COLAs Online, would let an applicant fix a title-case "Government Warning" before an agent ever sees it. Fewer corrections sent back and forth means less agent time; that is the biggest saving available. It is safe because the app never says Matches on a problem it can see, and it lists what it cannot check.
9. **Use what COLA already knows.** Every COLA record gives each label's real size, so the type-size check (27 CFR 16.22) would run on every application without anyone typing the label height.
10. **Track which version of the rules decided.** Every result would record the version of the rules and the date of the regulation text it used. A scheduled test would compare the warning text and other values in the code with the current eCFR, so a change in the regulations fails a test instead of going unnoticed.

**Enterprise needs.** I would add these before production:
- Sign-in through agency single sign-on (PIV/CAC).
- An audit log of who checked what and when, with records kept as the agency's rules require.
- Section 508 accessibility review.
- Monitoring, an authority to operate (ATO) for the system, and load testing at TTB's real volumes.

**What I don't know from outside.** These answers would shape my production design (more in [`APPROACH.md`](APPROACH.md)):
- Which cloud and AI services TTB has approved.
- What access the app could have to COLA data.
- Real daily volumes.
- Which boxes agents most want filled in for them.
