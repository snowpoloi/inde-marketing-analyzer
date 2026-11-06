// The email of a proposal, ready for the owner to send. Standalone (no imports) so the node tests can load it.

type EmailParts = { message_subject: string; message_body: string };

// What «Αντιγραφή email» puts on the clipboard: the subject line, a blank line, then the body.
export function proposalEmailText(proposal: EmailParts) {
  return proposal.message_subject ? `Θέμα: ${proposal.message_subject}\n\n${proposal.message_body}` : proposal.message_body;
}

// «Άνοιγμα στο email»: subject and body, no recipient, so the owner picks the address in their mail program.
export function proposalMailto(proposal: EmailParts) {
  const body = proposal.message_body.replace(/\r?\n/g, "\r\n");
  return `mailto:?subject=${encodeURIComponent(proposal.message_subject)}&body=${encodeURIComponent(body)}`;
}
