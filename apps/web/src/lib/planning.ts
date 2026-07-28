import type { PlanningProposalResponse } from "@/generated/api-schema";

type ProposalIdentity = Pick<
  PlanningProposalResponse,
  "diagnostic_session_id" | "status"
>;

export function isCurrentDiagnosticProposal(
  proposal: ProposalIdentity | null,
  diagnosticSessionId: string | undefined,
): boolean {
  return (
    proposal !== null &&
    diagnosticSessionId !== undefined &&
    proposal.diagnostic_session_id === diagnosticSessionId &&
    proposal.status !== "rejected"
  );
}
