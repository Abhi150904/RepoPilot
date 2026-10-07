import {
  BadgeCheck,
  Bot,
  Braces,
  Clock3,
  Code2,
  GitBranch,
  GitPullRequestArrow,
  Play,
  Radar,
  ShieldCheck,
  Sparkles,
  TestTube2,
  TimerReset,
  TriangleAlert,
  UserCheck
} from "lucide-react";

export const stages = [
  { label: "Analyze", state: "done" },
  { label: "Retrieve", state: "done" },
  { label: "Plan", state: "done" },
  { label: "Code", state: "done" },
  { label: "Test", state: "done" },
  { label: "Review", state: "done" },
  { label: "Approve", state: "active" }
] as const;

export const activeRuns = [
  {
    repo: "Abhi150904/RepoPilot",
    issue: "#42 Harden publication lifecycle",
    status: "Awaiting approval",
    elapsed: "3m 18s",
    accent: "amber"
  },
  {
    repo: "Abhi150904/Wandr",
    issue: "#16 Destination field crash",
    status: "Testing repair",
    elapsed: "1m 44s",
    accent: "cyan"
  },
  {
    repo: "OrbitLabs/api",
    issue: "#88 Resume failed publish",
    status: "Repository retrieval",
    elapsed: "48s",
    accent: "violet"
  }
];

export const metrics = [
  {
    label: "Engineering velocity",
    value: "12",
    suffix: "runs today",
    context: "+18% from yesterday",
    icon: Sparkles
  },
  {
    label: "Approval quality",
    value: "83%",
    suffix: "human approval rate",
    context: "reviewed at the final gate",
    icon: UserCheck
  },
  {
    label: "Autonomous resolution",
    value: "72%",
    suffix: "without repair",
    context: "clean first-pass completions",
    icon: Bot
  },
  {
    label: "Median runtime",
    value: "2m",
    suffix: "41s",
    context: "issue to reviewed patch",
    icon: Clock3
  }
];

export const timeline = [
  { label: "Issue analysis", icon: Radar, state: "complete", detail: "Intent and risk extracted" },
  { label: "Repository retrieval", icon: Braces, state: "complete", detail: "Hybrid retrieval ranked targets" },
  { label: "Implementation plan", icon: Play, state: "complete", detail: "4-step hardening plan" },
  { label: "Code generation", icon: Code2, state: "complete", detail: "2 files changed" },
  { label: "Tests", icon: TestTube2, state: "complete", detail: "26 tests passed" },
  { label: "Repair", icon: TimerReset, state: "muted", detail: "No repair needed" },
  { label: "Automated review", icon: ShieldCheck, state: "complete", detail: "0 blockers" },
  { label: "Human approval", icon: UserCheck, state: "active", detail: "Waiting for decision" },
  { label: "Publication", icon: GitPullRequestArrow, state: "locked", detail: "Locked until approval" }
];

export const planSteps = [
  "Bind approval to exact workspace state",
  "Revalidate Git safety before publication",
  "Serialize lifecycle transitions",
  "Resume partial publications safely"
];

export const diffLines = [
  { kind: "context", text: "def publish_run(self, run_id: str, request: PublishRequest) -> RunStatusResponse:" },
  { kind: "add", text: "    with self._transition_lock:" },
  { kind: "add", text: "        _validate_approval_binding(result)" },
  { kind: "remove", text: "    package = _publication_package(result, approval)" },
  { kind: "add", text: "        package = _publication_package(result, approval)" },
  { kind: "add", text: "        publish_result = _publish(package=package, previous=_publish_result(result))" }
];

export const verification = [
  "Workspace verified",
  "Tests passed",
  "Review passed",
  "HEAD bound",
  "Artifact unchanged"
];

export const publishModes = [
  { title: "Pull Request", label: "Recommended", icon: GitPullRequestArrow },
  { title: "Push Branch", label: "Remote branch", icon: GitBranch },
  { title: "Local Commit", label: "No remote side effects", icon: Code2 },
  { title: "Dry Run", label: "Validate only", icon: BadgeCheck }
];

export const evalRows = [
  { name: "Keyword", recall: "0.91", mrr: "0.74", precision: "0.62", hit: "94%" },
  { name: "BM25", recall: "0.96", mrr: "0.81", precision: "0.68", hit: "97%" },
  { name: "Vector", recall: "0.82", mrr: "0.69", precision: "0.54", hit: "88%" },
  { name: "Hybrid", recall: "0.98", mrr: "0.88", precision: "0.73", hit: "99%" },
  { name: "Reranker", recall: "0.98", mrr: "0.92", precision: "0.78", hit: "99%" }
];

export const failure = {
  passed: 17,
  failed: 2,
  test: "test_publish_retry_after_commit",
  reason: "Expected push stage to resume after existing commit.",
  repair: "RepoPilot identified the failure as repairable.",
  attempt: "1 / 2"
};

export const cautionIcon = TriangleAlert;
