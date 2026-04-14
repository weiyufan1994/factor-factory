# pdf skill bridge plan

Current bridge mode:
1. External OpenClaw pdf tool call
2. Receive structured JSON response
3. Feed response text into `PdfSkillClient.parse_response`
4. Continue local pipeline

Planned next bridge:
- Add one wrapper entry that accepts `{pdf_path, prompt_name, model}`
- Execute OpenClaw `pdf` tool from orchestration boundary
- Capture raw response text
- Persist raw response alongside normalized intake
- Return `StructuredIntake`
