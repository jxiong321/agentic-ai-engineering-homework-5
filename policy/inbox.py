from harness.inbox import drain
from harness.formats import BOUNDARY
from policy.hook import append

class InboxClient:
    def __init__(self, ctx, client):
        self.ctx, self.client, self.messages = ctx, client, []

    def create(self, **request):
        for message in drain(self.ctx):
            match = BOUNDARY.fullmatch(message["text"])
            if match:
                append("policy/rules.jsonl", dict(run_id=self.ctx.run_id, effect="deny", path=match.group(1), stated_at=message["delivered_at"], message=message["text"]))
            else:
                self.messages.append({"role": "user", "content": message["text"]})
        request["messages"] = list(request.get("messages") or []) + self.messages
        return self.client.create(**request)

    def __getattr__(self, name):
        return getattr(self.client, name)
