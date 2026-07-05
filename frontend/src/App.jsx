import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"

// ─── Structured Response Components ─────────────────────────────────────────

function FieldPromptsCard({ structured, onSend }) {
	const [selections, setSelections] = useState({})
	const [inputValues, setInputValues] = useState({})
	if (!structured || structured.type !== "field_prompts") return null

	const isResourceSpecific = structured.mode === "resource_specific" && Array.isArray(structured.resources)
	const resourceGroups = isResourceSpecific
		? structured.resources
			.filter((resource) => Array.isArray(resource.fields) && resource.fields.length > 0)
			.map((resource) => ({
				resource_id: resource.resource_id,
				resource_type: resource.resource_type,
				scope: resource.resource_id || resource.resource_type || "resource",
				fields: resource.fields,
			}))
		: [{
			resource_id: structured.resource_id || null,
			resource_type: structured.resource_type || null,
			scope: "global",
			fields: structured.fields || [],
		}]

	const flatFields = resourceGroups.flatMap((group) =>
		group.fields.map((field) => ({ ...field, _scope: group.scope, _resource_id: group.resource_id }))
	)
	if (!flatFields.length) return null

	const fieldKey = (scope, fieldName) => `${scope}::${fieldName}`

	const selectOption = (scope, fieldName, value) => {
		setSelections((prev) => ({ ...prev, [fieldKey(scope, fieldName)]: value }))
	}

	const handleSubmitAll = () => {
		const parts = []
		for (const field of flatFields) {
			const key = fieldKey(field._scope, field.field_name)
			const selected = selections[key]
			const typed = inputValues[key]?.trim()
			if (selected) {
				parts.push(isResourceSpecific && field._resource_id
					? `${field.field_name}: ${selected} for ${field._resource_id}`
					: `${field.field_name}: ${selected}`)
			} else if (typed) {
				parts.push(isResourceSpecific && field._resource_id
					? `${field.field_name}: ${typed} for ${field._resource_id}`
					: `${field.field_name}: ${typed}`)
			} else if (field.allow_empty) {
				// skip optional fields that are empty
			}
		}
		if (parts.length > 0) {
			onSend(parts.join(", "))
			setSelections({})
			setInputValues({})
		}
	}

	const filledCount = flatFields.filter((f) => {
		const key = fieldKey(f._scope, f.field_name)
		return selections[key] || inputValues[key]?.trim()
	}).length
	const requiredCount = flatFields.filter((f) => !f.allow_empty).length
	const filledRequired = flatFields.filter((f) => {
		const key = fieldKey(f._scope, f.field_name)
		return !f.allow_empty && (selections[key] || inputValues[key]?.trim())
	}).length

	return (
		<div className="sc-card sc-field-prompts">
			<div className="sc-header">
				<span className="sc-icon">📋</span>
				<span>Fields needed to create requested resource{(structured.total_resources || 1) > 1 ? 's' : ''}</span>
				<span className="sc-badge sc-badge-collecting">{filledCount}/{flatFields.length}</span>
			</div>
			<div className="sc-fields-list">
				{resourceGroups.map((group) => (
					<div key={group.scope}>
						{isResourceSpecific && (
							<div className="sc-group-title">
								{(group.resource_type || "resource").toUpperCase()} ({group.resource_id || group.scope})
							</div>
						)}
						{group.fields.map((field) => {
							const key = fieldKey(group.scope, field.field_name)
							const isSelected = selections[key]
							return (
								<div key={key} className={`sc-field-row ${isSelected ? "sc-field-done" : ""}`}>
									<div className="sc-field-info">
										<span className="sc-field-name">{field.label || field.field_name}</span>
										{field.allow_empty && <span className="sc-badge sc-badge-optional">optional</span>}
										{isSelected && <span className="sc-badge sc-badge-done">✓ {isSelected}</span>}
									</div>
									{!isSelected && field.description && <div className="sc-field-desc">{field.description}</div>}
									{!isSelected && field.options && field.options.length > 0 && (
										<div className="sc-options-group">
											{field.options.map((opt) => {
												const val = typeof opt === "string" ? opt : opt.value
												const label = typeof opt === "string" ? opt : opt.label
												const desc = typeof opt === "string" ? null : opt.description
												return (
													<button
														key={`${key}::${val}`}
														type="button"
														className="sc-option-btn"
														onClick={() => selectOption(group.scope, field.field_name, val)}
														title={desc || label}
													>
														<span className="sc-option-label">{label}</span>
														{desc && <span className="sc-option-desc">{desc}</span>}
													</button>
												)
											})}
										</div>
									)}
									{!isSelected && !field.options && (
										<div className="sc-input-row">
											<input
												type="text"
												className="sc-text-input"
												placeholder={field.placeholder || `Enter ${field.label || field.field_name}...`}
												value={inputValues[key] || ""}
												onChange={(e) => setInputValues((prev) => ({ ...prev, [key]: e.target.value }))}
											/>
											{field.allow_empty && !inputValues[key]?.trim() && (
												<button type="button" className="sc-skip-btn" onClick={() => selectOption(group.scope, field.field_name, "(empty)")}>Skip</button>
											)}
										</div>
									)}
								</div>
							)
						})}
					</div>
				))}
			</div>
			<div className="sc-actions">
				<button
					type="button"
					className="sc-btn-confirm"
					onClick={handleSubmitAll}
					disabled={filledRequired < requiredCount}
				>
					Submit All Fields ({filledCount}/{flatFields.length})
				</button>
			</div>
		</div>
	)
}

function YamlPreviewCard({ structured, onSend }) {
	const [yamlTexts, setYamlTexts] = useState({})
	const [currentIdx, setCurrentIdx] = useState(0)

	if (!structured || structured.type !== "yaml_preview") return null

	// Support multiple resources via structured.resources array
	const resources = structured.resources || [{
		resource_id: structured.resource_id,
		resource_type: structured.resource_type,
		all_fields: structured.all_fields,
		editable_fields: structured.editable_fields,
		readonly_fields: structured.readonly_fields,
	}]

	const total = resources.length
	const current = resources[currentIdx] || resources[0]
	const readonlySet = new Set(current.readonly_fields || [])
	const allFields = current.all_fields || {}
	const resourceId = current.resource_id || "resource"

	// Build initial YAML text for current resource if not yet initialized
	if (!yamlTexts[resourceId] && Object.keys(allFields).length > 0) {
		const lines = Object.entries(allFields).map(([key, value]) => {
			const strVal = String(value ?? "")
			if (key === "aws_account_id" || key === "aws_region") {
				return `${key}: '${strVal}'`
			} else if (strVal === "") {
				return `${key}: ""`
			} else if (strVal.includes(" ") || strVal.includes(":") || strVal.includes("#")) {
				return `${key}: "${strVal}"`
			}
			return `${key}: ${strVal}`
		})
		setYamlTexts((prev) => ({ ...prev, [resourceId]: lines.join("\n") }))
	}

	const yamlText = yamlTexts[resourceId] || ""

	const handleConfirm = () => {
		// Parse the edited YAML and send changes back
		const editedFields = {}
		for (const line of yamlText.split("\n")) {
			const match = line.match(/^(\w+):\s*(.*)$/)
			if (match) {
				let val = match[2].trim()
				if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
					val = val.slice(1, -1)
				}
				editedFields[match[1]] = val
			}
		}

		const changes = []
		for (const [key, newVal] of Object.entries(editedFields)) {
			const origVal = String(allFields[key] ?? "")
			if (newVal !== origVal && !readonlySet.has(key)) {
				changes.push(`${key}: ${newVal}`)
			}
		}

		if (changes.length > 0) {
			onSend(`set ${changes.join(", ")} for ${resourceId}, then confirm`)
		} else {
			onSend(`confirm ${resourceId}`)
		}
	}

	const handleConfirmAll = () => {
		// Collect changes from all resources and confirm all at once
		const allChanges = []
		for (const res of resources) {
			const resYaml = yamlTexts[res.resource_id] || ""
			const resFields = res.all_fields || {}
			const resReadonly = new Set(res.readonly_fields || [])
			for (const line of resYaml.split("\n")) {
				const match = line.match(/^(\w+):\s*(.*)$/)
				if (match) {
					let val = match[2].trim()
					if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
						val = val.slice(1, -1)
					}
					const origVal = String(resFields[match[1]] ?? "")
					if (val !== origVal && !resReadonly.has(match[1])) {
						allChanges.push(`${match[1]}: ${val}`)
					}
				}
			}
		}
		if (allChanges.length > 0) {
			onSend(`set ${allChanges.join(", ")}, then confirm all`)
		} else {
			onSend("confirm all")
		}
	}

	const lockedNames = (current.readonly_fields || []).join(", ")

	return (
		<div className="sc-card sc-yaml-editor">
			<div className="sc-yaml-tab">
				<span className="sc-yaml-tab-icon">📄</span>
				<span className="sc-yaml-tab-name">{resourceId}.yaml</span>
				<span className="sc-badge sc-badge-confirming">review</span>
				{total > 1 && (
					<span className="sc-pagination">
						<button
							type="button"
							className="sc-page-btn"
							disabled={currentIdx === 0}
							onClick={() => setCurrentIdx((i) => i - 1)}
						>
							◀
						</button>
						<span className="sc-page-info">{currentIdx + 1} / {total}</span>
						<button
							type="button"
							className="sc-page-btn"
							disabled={currentIdx === total - 1}
							onClick={() => setCurrentIdx((i) => i + 1)}
						>
							▶
						</button>
					</span>
				)}
			</div>
			<div className="sc-yaml-editor-body">
				<textarea
					className="sc-yaml-textarea"
					value={yamlText}
					onChange={(e) => setYamlTexts((prev) => ({ ...prev, [resourceId]: e.target.value }))}
					spellCheck={false}
					rows={Math.max(Object.keys(allFields).length + 1, 8)}
				/>
			</div>
			<div className="sc-yaml-footer">
				<span className="sc-yaml-hint">🔒 Locked: {lockedNames}</span>
				<div className="sc-actions">
					{total > 1 && (
						<button type="button" className="sc-btn-confirm sc-btn-confirm-all" onClick={handleConfirmAll}>
							✓ Confirm All ({total})
						</button>
					)}
					<button type="button" className="sc-btn-confirm" onClick={handleConfirm}>
						✓ Confirm{total > 1 ? ` This` : ` & Submit`}
					</button>
					<button type="button" className="sc-btn-cancel" onClick={() => onSend(`cancel ${resourceId}`)}>
						Cancel
					</button>
				</div>
			</div>
		</div>
	)
}

function UpdateDiffCard({ structured, onSend }) {
	const [updatedYaml, setUpdatedYaml] = useState(structured?.updated_yaml || "")
	const [targetBranch, setTargetBranch] = useState(structured?.branch || "")

	if (!structured || structured.type !== "update_diff") return null

	const filePath = structured.file_path || "resource.yaml"
	const diff = structured.diff || ""
	const appendOnlyValid = Boolean(structured.append_only_valid)

	const handleSubmitEdited = () => {
		onSend?.(
			`I edited the proposed update for ${filePath}. Use stage_full_updated_yaml to validate this full updated YAML as append-only and show the diff again:\n\n\`\`\`yaml\n${updatedYaml}\n\`\`\``
		)
	}

	const handleCreatePr = () => {
		const branchText = targetBranch.trim()
		onSend?.(branchText
			? `The update diff looks good. Create update PR to branch ${branchText}.`
			: "The update diff looks good. Create update PR.")
	}

	return (
		<div className="sc-card sc-update-diff-card">
			<div className="sc-header">
				<span className="sc-icon">🧩</span>
				<span>Update Diff</span>
				<span className={`sc-badge ${appendOnlyValid ? "sc-badge-done" : "sc-badge-reviewing"}`}>
					{appendOnlyValid ? "append-only" : "needs review"}
				</span>
			</div>
			<div className="sc-update-meta">
				<div><strong>File:</strong> {filePath}</div>
				<div><strong>Resource:</strong> {(structured.resource_type || "resource").toUpperCase()}</div>
			</div>
			<div className="sc-yaml-editor-body">
				<textarea
					className="sc-yaml-textarea"
					value={updatedYaml}
					onChange={(event) => setUpdatedYaml(event.target.value)}
					spellCheck={false}
					rows={Math.max(updatedYaml.split("\n").length + 1, 10)}
				/>
			</div>
			<div className="sc-diff-block">
				<div className="sc-yaml-block-header">
					<span>git diff</span>
				</div>
				<pre className="sc-diff-pre">{diff}</pre>
			</div>
			<div className="sc-update-branch-row">
				<input
					type="text"
					className="sc-text-input"
					placeholder="Target branch for PR"
					value={targetBranch}
					onChange={(event) => setTargetBranch(event.target.value)}
				/>
			</div>
			<div className="sc-actions">
				<button type="button" className="sc-btn-confirm" onClick={handleCreatePr} disabled={!appendOnlyValid}>
					Create Update PR
				</button>
				<button type="button" className="sc-btn-cancel" onClick={handleSubmitEdited}>
					Validate Edited YAML
				</button>
			</div>
		</div>
	)
}

function ResourcePanel({ resources, onCopyYaml }) {
	const [expanded, setExpanded] = useState({})
	if (!resources || !resources.length) return null

	const toggle = (id) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))

	return (
		<div className="sc-resource-panel">
			{resources.map((r) => (
				<div key={r.resource_id} className={`sc-resource-card sc-status-${r.status}`}>
					<div className="sc-resource-header">
						<span className="sc-resource-title">{r.title}</span>
						<span className={`sc-badge sc-badge-${r.status}`}>{r.status}</span>
					</div>
					<div className="sc-resource-fields">
						{Object.entries(r.all_fields || {}).slice(0, 4).map(([k, v]) => (
							<div key={k} className="sc-rf">
								<span className="sc-rf-k">{k}:</span>
								<span className="sc-rf-v">{String(v)}</span>
							</div>
						))}
						{Object.keys(r.all_fields || {}).length > 4 && (
							<div className="sc-rf sc-rf-more">+{Object.keys(r.all_fields).length - 4} more fields</div>
						)}
					</div>
					{r.yaml && (
						<div className="sc-resource-yaml-section">
							<button type="button" className="sc-yaml-toggle" onClick={() => toggle(r.resource_id)}>
								{expanded[r.resource_id] ? "▾ Hide YAML" : "▸ View YAML"}
							</button>
							{expanded[r.resource_id] && (
								<div className="sc-yaml-block">
									<div className="sc-yaml-block-header">
										<span>yaml</span>
										<button type="button" className="sc-copy-btn" onClick={() => onCopyYaml(r.yaml)}>Copy</button>
									</div>
									<pre className="sc-yaml-pre">{r.yaml}</pre>
								</div>
							)}
						</div>
					)}
				</div>
			))}
		</div>
	)
}

function shouldShowDataOwnerApprovalUpload(messageText) {
	const text = String(messageText || "").toLowerCase()
	const alreadyResolved = text.includes("approval validated")
		|| text.includes("approval verified")
		|| text.includes("data owner approval validated")
		|| text.includes("data-owner approval validated")
		|| text.includes("data owner approval verified")
		|| text.includes("data-owner approval verified")
		|| text.includes("created (")
		|| text.includes("created glue")
	if (alreadyResolved) return false

	const mentionsApproval = text.includes("data-owner approval")
		|| text.includes("data owner approval")
		|| text.includes("approval")
	const requestsEvidence = text.includes("upload")
		|| text.includes("pdf")
		|| text.includes("screenshot")
		|| text.includes("file_id")
		|| text.includes("requires")
		|| text.includes("needs")
		|| text.includes("before i can")
		|| text.includes("before creation")
	return mentionsApproval && requestsEvidence
}

function inferDataOwnerApprovalResourceTypes(messageText, approvalRequirements = {}) {
	const text = String(messageText || "").toLowerCase()
	const configured = Array.isArray(approvalRequirements.resources) ? approvalRequirements.resources : []
	const matched = configured.filter((resourceType) => {
		const value = String(resourceType || "").toLowerCase()
		if (!value) return false
		if (text.includes(value)) return true
		if (value === "glue_db" && (text.includes("glue db") || text.includes("glue database") || text.includes("gluedb"))) return true
		return false
	})
	if (matched.length > 0) return matched
	if (configured.length === 1 && shouldShowDataOwnerApprovalUpload(text)) return configured
	return []
}

function fileToBase64(file) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader()
		reader.onload = () => {
			const result = String(reader.result || "")
			resolve(result.includes(",") ? result.split(",").pop() : result)
		}
		reader.onerror = () => reject(reader.error || new Error("Could not read file"))
		reader.readAsDataURL(file)
	})
}

function DataOwnerApprovalUploadCard({ messageText, approvalRequirements, resourceTypesOverride, currentChatId, intakeId, onUpload, onSend }) {
	const [file, setFile] = useState(null)
	const [status, setStatus] = useState(null)
	const [error, setError] = useState("")
	const [uploading, setUploading] = useState(false)

	const overrideResourceTypes = Array.isArray(resourceTypesOverride)
		? resourceTypesOverride.filter(Boolean)
		: []
	if (!overrideResourceTypes.length && !shouldShowDataOwnerApprovalUpload(messageText)) return null

	const resourceTypes = overrideResourceTypes.length
		? overrideResourceTypes
		: inferDataOwnerApprovalResourceTypes(messageText, approvalRequirements)
	if (!resourceTypes.length) return null

	const acceptedTypes = Array.isArray(approvalRequirements?.accepted_file_types)
		? approvalRequirements.accepted_file_types
		: ["image/png", "image/jpeg", "image/jpg", "application/pdf"]
	const acceptAttr = acceptedTypes.join(",")
	const resourceLabel = resourceTypes.map((resourceType) => resourceType.replace(/_/g, " ").toUpperCase()).join(", ")

	const handleUpload = async () => {
		if (!file || uploading) return
		if (acceptedTypes.length && !acceptedTypes.includes(file.type)) {
			setError(`Unsupported file type: ${file.type || "unknown"}. Upload PDF, PNG, or JPG.`)
			return
		}

		try {
			setError("")
			setStatus(null)
			setUploading(true)
			const fileContentBase64 = await fileToBase64(file)
			const result = await onUpload({
				resource_types: resourceTypes,
				session_id: currentChatId,
				intake_id: intakeId || null,
				file_name: file.name,
				file_type: file.type,
				file_content_base64: fileContentBase64,
			})
			setStatus(result)
			await onSend?.(
				`I uploaded a data owner approval document for ${resourceTypes.join(", ")}. `
				+ `file_id: ${result.file_id}. file_name: ${result.file_name}. `
				+ `Please validate it and continue.`
			)
		} catch (uploadError) {
			setError(uploadError.message || "Approval upload failed")
		} finally {
			setUploading(false)
		}
	}

	const handleSkip = () => {
		onSend?.(`Skip ${resourceTypes.join(", ")} from this request and continue with the remaining resources.`)
	}

	return (
		<div className="sc-card approval-upload-card">
			<div className="sc-header">
				<span className="sc-icon">📎</span>
				<span>Upload Data Owner Approval</span>
				<span className="sc-badge sc-badge-confirming">{resourceLabel}</span>
			</div>
			<div className="approval-upload-body">
				<p>Upload the approval PDF or screenshot. The agent will validate it before continuing. If you do not have it now, skip this resource and continue with the rest.</p>
				<label className={`approval-dropzone ${file ? "has-file" : ""}`}>
					<input
						type="file"
						accept={acceptAttr}
						onChange={(event) => {
							setFile(event.target.files?.[0] || null)
							setStatus(null)
							setError("")
						}}
						disabled={uploading || status?.uploaded}
					/>
					<span className="approval-dropzone-title">{file ? file.name : "Choose PDF, PNG, or JPG"}</span>
					<span className="approval-dropzone-subtitle">Accepted: {acceptedTypes.join(", ")}</span>
				</label>
				{error && <div className="approval-upload-result approval-error">{error}</div>}
				{status?.uploaded && <div className="approval-upload-result approval-success">✓ Uploaded. Asking the agent to validate this document.</div>}
			</div>
			<div className="sc-actions">
				<button type="button" className="sc-btn-confirm" onClick={handleUpload} disabled={!file || uploading || status?.uploaded}>
					{uploading ? "Uploading..." : "Upload for Agent Validation"}
				</button>
				<button type="button" className="sc-btn-cancel" onClick={handleSkip} disabled={uploading}>
					Skip {resourceLabel}
				</button>
			</div>
		</div>
	)
}

// ─── Starter Cards ──────────────────────────────────────────────────────────

const STARTER_CARDS = [
	{
		id: "s3",
		title: "Provision an S3 Bucket",
		description: "Launch an approval-ready S3 request with naming, policy, and location guidance.",
		prompt: "I need to create an S3 bucket for analytics exports in dev.",
		sampleUser: "Create an S3 bucket for finance exports in us-east dev.",
		sampleAssistant: "Done. I will collect the bucket details and prepare a PR-ready YAML.",
	},
	{
		id: "glue",
		title: "Create a Glue Database",
		description: "Generate a Glue DB request aligned to enterprise naming conventions and validations.",
		prompt: "I need a Glue database for customer analytics in prod.",
		sampleUser: "Create a Glue database for customer analytics in prod.",
		sampleAssistant: "I can guide you field by field and validate the naming rules before PR creation.",
	},
	{
		id: "iam",
		title: "Build an IAM Role",
		description: "Draft an IAM role request with clear ownership, purpose, and policy expectations.",
		prompt: "I need an IAM role for a nightly ETL workflow.",
		sampleUser: "Create an IAM role for a nightly ETL workflow.",
		sampleAssistant: "Prepared. I will gather trust, permissions, and ownership metadata step by step.",
	},
	{
		id: "resume",
		title: "Continue Existing Work",
		description: "Resume a previous provisioning conversation from the history panel on the left.",
		prompt: "Show me where we left off and help me continue.",
		sampleUser: "Continue my last infrastructure request.",
		sampleAssistant: "Loaded. Your previous progress is available from history and can continue from the last step.",
	},
]

function formatTime(ts) {
	if (!ts) return ""
	try {
		return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
	} catch {
		return ""
	}
}

function escapeHtml(str) {
	const div = document.createElement("div")
	div.appendChild(document.createTextNode(str || ""))
	return div.innerHTML
}

function escapeAttr(str) {
	return (str || "")
		.replace(/&/g, "&amp;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
}

function formatContent(text) {
	let html = escapeHtml(text)
	html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
		const label = lang || "yaml"
		return `<div class="code-block"><div class="code-header"><span>${label}</span><button class="copy-btn" data-code="${escapeAttr(code.trim())}">Copy</button></div><pre>${escapeHtml(code.trim())}</pre></div>`
	})
	html = html.replace(/`([^`]+)`/g, "<code>$1</code>")
	html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
	html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>")
	html = html.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
	html = html.replace(/\n/g, "<br>")
	return html
}

function inferResourceChoiceOptions(messageText, existingOptions, supportedResources = []) {
	if (Array.isArray(existingOptions) && existingOptions.length > 0) {
		return { options: existingOptions, options_multi_select: false }
	}

	const text = String(messageText || "").toLowerCase()
	const mentionsS3 = text.includes("s3") || text.includes("s3 bucket")
	const mentionsGlue = text.includes("glue_db")
		|| text.includes("glue db")
		|| text.includes("glue database")
		|| text.includes("gluedb")
	const asksResourceChoice =
		text.includes("which resource would you like to create")
		|| text.includes("what would you like to create")
		|| text.includes("which one would you like")
		|| text.includes("reply with \"s3\"")
		|| text.includes("reply with s3")
		|| (mentionsS3 && mentionsGlue && (text.includes("which") || text.includes("what") || text.includes(" or ")))

	if (!asksResourceChoice) {
		return { options: null, options_multi_select: false }
	}

	const normalizedSupported = Array.isArray(supportedResources)
		? supportedResources
			.filter((resource) => resource && resource.type)
			.map((resource) => ({
				value: String(resource.type),
				label: String(resource.display || resource.type),
				description: `Create a ${String(resource.display || resource.type)}`,
			}))
		: []

	if (normalizedSupported.length > 0) {
		return {
			options: normalizedSupported,
			options_multi_select: true,
		}
	}

	return {
		options: [
			{ value: "s3", label: "S3 Bucket", description: "Create an S3 bucket" },
			{ value: "glue_db", label: "Glue DB", description: "Create a Glue Database" },
		],
		options_multi_select: true,
	}
}

function MessageBubble({ message, isLatest, onOptionClick, approvalRequirements, currentChatId, intakeId, onValidateApprovalUpload }) {
	const [selected, setSelected] = useState(new Set())
	const [isAssistantCollapsed, setIsAssistantCollapsed] = useState(false)

	const structuredType = message?.structured?.type
	const approvalResourceTypes = structuredType === "approval_required" && Array.isArray(message.structured?.resource_types)
		? message.structured.resource_types
		: inferDataOwnerApprovalResourceTypes(message.content, approvalRequirements)
	const hasApprovalUploadUI = Boolean(
		message.role === "assistant"
		&& isLatest
		&& (
			structuredType === "approval_required"
			|| shouldShowDataOwnerApprovalUpload(message.content)
		)
		&& approvalResourceTypes.length > 0
	)
	const hasStructuredHelperUI = structuredType === "field_prompts" || structuredType === "yaml_preview" || structuredType === "update_diff"
	const hasHelperUI = Boolean(
		message.role === "assistant"
		&& isLatest
		&& (
			hasStructuredHelperUI
			|| hasApprovalUploadUI
			|| (Array.isArray(message.options) && message.options.length > 0)
		)
	)

	useEffect(() => {
		setIsAssistantCollapsed(hasHelperUI)
	}, [hasHelperUI, message.id])

	const handleCopyClick = useCallback((event) => {
		const button = event.target.closest(".copy-btn")
		if (!button) return
		navigator.clipboard.writeText(button.dataset.code || "").then(() => {
			const original = button.textContent
			button.textContent = "Copied!"
			setTimeout(() => {
				button.textContent = original
			}, 1200)
		}).catch(() => {})
	}, [])

	const handleOptionSelect = useCallback((value) => {
		if (!message.options_multi_select) {
			onOptionClick?.(value)
			return
		}

		setSelected((current) => {
			const next = new Set(current)
			if (next.has(value)) next.delete(value)
			else next.add(value)
			return next
		})
	}, [message.options_multi_select, onOptionClick])

	const submitMultiSelect = useCallback(() => {
		if (!selected.size) return
		onOptionClick?.(Array.from(selected).join(", "))
		setSelected(new Set())
	}, [onOptionClick, selected])

	const handleCopyYaml = useCallback((yaml) => {
		navigator.clipboard.writeText(yaml).catch(() => {})
	}, [])

	return (
		<div className={`msg msg-${message.role}`}>
			{message.role === "assistant" && hasHelperUI && (
				<div className="assistant-collapse-wrap">
					<button
						type="button"
						className="assistant-collapse-btn"
						onClick={() => setIsAssistantCollapsed((current) => !current)}
					>
						{isAssistantCollapsed ? "Show assistant message" : "Hide assistant message"}
					</button>
				</div>
			)}

			{(!hasHelperUI || !isAssistantCollapsed) ? (
				<div className="msg-bubble" onClick={handleCopyClick}>
					{message.role === "assistant"
						? <div className="markdown-body" dangerouslySetInnerHTML={{ __html: formatContent(message.content) }} />
						: message.content}
				</div>
			) : (
				<div className="msg-bubble msg-bubble-collapsed">Assistant message is collapsed while helper UI is shown.</div>
			)}

			{/* Structured components — only on latest assistant message */}
			{message.role === "assistant" && isLatest && message.structured && (
				<>
					<FieldPromptsCard structured={message.structured} onSend={onOptionClick} />
					<YamlPreviewCard structured={message.structured} onSend={onOptionClick} />
					<UpdateDiffCard structured={message.structured} onSend={onOptionClick} />
				</>
			)}

			{message.role === "assistant" && isLatest && hasApprovalUploadUI && (
				<DataOwnerApprovalUploadCard
					messageText={message.content}
					approvalRequirements={approvalRequirements}
					resourceTypesOverride={approvalResourceTypes}
					currentChatId={currentChatId}
					intakeId={intakeId}
					onUpload={onValidateApprovalUpload}
					onSend={onOptionClick}
				/>
			)}

			{/* Resource panel — on latest assistant message when resources exist */}
			{message.role === "assistant" && isLatest && message.resources_summary && message.resources_summary.length > 0 && (
				<ResourcePanel resources={message.resources_summary} onCopyYaml={handleCopyYaml} />
			)}

			{message.role === "assistant" && isLatest && Array.isArray(message.options) && message.options.length > 0 && (
				<div className="options-grid">
					{message.options.map((option, index) => {
						const isSelected = selected.has(option.value)
						return (
							<button
								key={`${option.value}-${index}`}
								type="button"
								className={`option-btn${isSelected ? " selected" : ""}`}
								onClick={() => handleOptionSelect(option.value)}
								title={option.description || option.label}
							>
								<span className="option-label-row">
									{message.options_multi_select && <span className="option-check">{isSelected ? "☑" : "☐"}</span>}
									<span className="option-label">{option.label}</span>
								</span>
								{option.description && <span className="option-desc">{option.description}</span>}
							</button>
						)
					})}
					{message.options_multi_select && (
						<button type="button" className="option-btn option-submit" onClick={submitMultiSelect} disabled={!selected.size}>
							<span className="option-label">Confirm Selection</span>
						</button>
					)}
				</div>
			)}
		</div>
	)
}

export default function App() {
	const [isLoading, setIsLoading] = useState(true)
	const [isAuthenticated, setIsAuthenticated] = useState(false)
	const [githubUser, setGithubUser] = useState("")
	const [authError, setAuthError] = useState("")
	const [errorText, setErrorText] = useState("")
	const [draft, setDraft] = useState("")
	const [messages, setMessages] = useState([])
	const [chats, setChats] = useState([])
	const [currentChatId, setCurrentChatId] = useState(null)
	const [sidebarOpen, setSidebarOpen] = useState(true)
	const [historyMenuId, setHistoryMenuId] = useState(null)
	const [showTemplates, setShowTemplates] = useState(true)
	const [sending, setSending] = useState(false)
	const [supportedResources, setSupportedResources] = useState([])
	const [approvalRequirements, setApprovalRequirements] = useState({})
	const textareaRef = useRef(null)
	const threadEndRef = useRef(null)
	const hasActiveSession = currentChatId !== null

	const helperText = useMemo(() => {
		if (hasActiveSession) return "Session started. Continue your conversation below."
		return "Choose a MINI starter to begin quickly, or start a new chat from the history panel."
	}, [hasActiveSession])

	useEffect(() => {
		threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
	}, [messages, sending])

	useEffect(() => {
		if (!historyMenuId) return undefined
		const onDocumentClick = () => setHistoryMenuId(null)
		document.addEventListener("click", onDocumentClick)
		return () => document.removeEventListener("click", onDocumentClick)
	}, [historyMenuId])

	const api = useCallback(async (path, options = {}, userOverride = null) => {
		const headers = {
			...(options.body ? { "Content-Type": "application/json" } : {}),
			...(options.headers || {}),
		}
		const actingUser = userOverride || githubUser
		if (actingUser) headers["X-GitHub-User"] = actingUser

		const response = await fetch(path, { ...options, headers })
		if (!response.ok) {
			let message = "Request failed"
			try {
				const payload = await response.json()
				message = payload.detail || payload.error || message
			} catch {
			}
			throw new Error(message)
		}
		if (response.status === 204) return null
		return response.json()
	}, [githubUser])

	const mapMessages = useCallback((payload = []) => (
		payload.map((item) => ({
			id: String(item.id),
			role: item.role,
			content: item.content,
			created_at: item.created_at,
			options: item.metadata_json?.options || null,
			options_multi_select: Boolean(item.metadata_json?.options_multi_select),
		}))
	), [])

	const loadChat = useCallback(async (chatId, userOverride = null) => {
		if (!chatId) {
			setCurrentChatId(null)
			setMessages([])
			setShowTemplates(true)
			return
		}

		const payload = await api(`/api/chats/${chatId}/messages`, {}, userOverride)
		const nextMessages = mapMessages(payload || [])
		setCurrentChatId(String(chatId))
		setMessages(nextMessages)
		setShowTemplates(nextMessages.length === 0)
		setErrorText("")
	}, [api, mapMessages])

	const loadChats = useCallback(async (userOverride = null, preferredChatId = null) => {
		const payload = await api("/api/chats", {}, userOverride)
		const nextChats = payload?.chats || []
		setChats(nextChats)

		const selectedChatId = preferredChatId
			|| (currentChatId && nextChats.some((chat) => String(chat.id) === String(currentChatId)) ? currentChatId : null)
			|| nextChats[0]?.id

		if (selectedChatId) {
			await loadChat(selectedChatId, userOverride)
		} else {
			setCurrentChatId(null)
			setMessages([])
			setShowTemplates(true)
		}

		return nextChats
	}, [api, currentChatId, loadChat])

	const loadSupportedResources = useCallback(async (userOverride = null) => {
		try {
			const payload = await api("/api/resources/supported", {}, userOverride)
			setSupportedResources(payload?.resources || [])
		} catch {
			setSupportedResources([])
		}
	}, [api])

	const loadApprovalRequirements = useCallback(async (userOverride = null) => {
		try {
			const payload = await api("/api/data-owner-approval/requirements", {}, userOverride)
			setApprovalRequirements(payload || {})
		} catch {
			setApprovalRequirements({})
		}
	}, [api])

	useEffect(() => {
		const init = async () => {
			try {
				const params = new URLSearchParams(window.location.search)

				if (params.get("auth") === "success" && params.get("github_user")) {
					const user = params.get("github_user")
					localStorage.setItem("github_user", user)
					setGithubUser(user)
					setIsAuthenticated(true)
					window.history.replaceState({}, "", "/")
					await loadSupportedResources(user)
					await loadApprovalRequirements(user)
					await loadChats(user)
					return
				}

				if (params.get("auth_error")) {
					window.history.replaceState({}, "", "/")
					setAuthError("GitHub authentication failed. Please try again.")
					return
				}

				const savedUser = localStorage.getItem("github_user")
				if (!savedUser) return

				const auth = await api("/auth/me", { headers: { "X-GitHub-User": savedUser } }, savedUser)
				if (!auth?.authenticated) {
					localStorage.removeItem("github_user")
					return
				}

				setGithubUser(savedUser)
				setIsAuthenticated(true)
				await loadSupportedResources(savedUser)
				await loadApprovalRequirements(savedUser)
				await loadChats(savedUser)
			} catch {
				localStorage.removeItem("github_user")
			} finally {
				setIsLoading(false)
			}
		}

		init()
	}, [api, loadChats, loadSupportedResources, loadApprovalRequirements])

	const startNewChat = useCallback(async () => {
		try {
			setErrorText("")
			const chat = await api("/api/chats", { method: "POST" })
			setChats((current) => [chat, ...current])
			setCurrentChatId(String(chat.id))
			setMessages([])
			setDraft("")
			setShowTemplates(true)
			setHistoryMenuId(null)
			if (textareaRef.current) textareaRef.current.style.height = "auto"
		} catch (error) {
			setErrorText(error.message)
		}
	}, [api])

	const deleteChat = useCallback(async (chatId) => {
		setHistoryMenuId(null)
		if (!window.confirm("Delete this chat from history?")) return

		try {
			await api(`/api/chats/${chatId}`, { method: "DELETE" })
			const remaining = chats.filter((chat) => String(chat.id) !== String(chatId))
			setChats(remaining)

			if (String(currentChatId) === String(chatId)) {
				if (remaining.length > 0) {
					await loadChat(remaining[0].id)
				} else {
					setCurrentChatId(null)
					setMessages([])
					setShowTemplates(true)
				}
			}
		} catch (error) {
			setErrorText(error.message)
		}
	}, [api, chats, currentChatId, loadChat])

	const logout = useCallback(() => {
		localStorage.removeItem("github_user")
		setIsAuthenticated(false)
		setGithubUser("")
		setChats([])
		setMessages([])
		setDraft("")
		setCurrentChatId(null)
		setShowTemplates(true)
		setHistoryMenuId(null)
		setAuthError("")
		setErrorText("")
	}, [])

	const uploadApprovalDocument = useCallback(async (payload) => {
		return api("/api/data-owner-approval/upload", {
			method: "POST",
			body: JSON.stringify(payload),
		})
	}, [api])

	const useStarterPrompt = useCallback(async (prompt) => {
		if (!currentChatId) {
			await startNewChat()
		}
		setDraft(prompt)
		requestAnimationFrame(() => textareaRef.current?.focus())
	}, [currentChatId, startNewChat])

	const updateComposerHeight = useCallback((value) => {
		setDraft(value)
		if (!textareaRef.current) return
		textareaRef.current.style.height = "auto"
		textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`
	}, [])

	const sendMessage = useCallback(async (eventOrText) => {
		if (eventOrText?.preventDefault) eventOrText.preventDefault()
		const text = typeof eventOrText === "string" ? eventOrText : draft
		const trimmed = text.trim()
		if (!trimmed || sending) return

		try {
			setErrorText("")
			let workingChatId = currentChatId

			if (!workingChatId) {
				const chat = await api("/api/chats", { method: "POST" })
				workingChatId = String(chat.id)
				setChats((current) => [chat, ...current])
				setCurrentChatId(workingChatId)
			}

			setMessages((current) => [
				...current,
				{ id: `user-${Date.now()}`, role: "user", content: trimmed },
			])
			setShowTemplates(false)
			setSending(true)
			setDraft("")
			if (textareaRef.current) textareaRef.current.style.height = "auto"

			const payload = await api("/api/chat", {
				method: "POST",
				body: JSON.stringify({ message: trimmed, session_id: workingChatId }),
			})

			// Build content: just the message text (YAML shown in resource cards)
			let content = payload.message
			const inferredOptions = inferResourceChoiceOptions(content, payload.options || null, supportedResources)

			setMessages((current) => [
				...current,
				{
					id: `assistant-${Date.now()}`,
					role: "assistant",
					content,
					options: inferredOptions.options,
					options_multi_select: Boolean(payload.options_multi_select || inferredOptions.options_multi_select),
					structured: payload.structured || null,
					resources_summary: payload.resources_summary || null,
				},
			])

			setChats((current) => {
				const chatId = payload.session_id || workingChatId
				const existing = current.find((chat) => String(chat.id) === String(chatId))
				const updated = {
					id: chatId,
					title: payload.chat_title || existing?.title || trimmed.slice(0, 48) || "New Chat",
					created_at: existing?.created_at || payload.updated_at || new Date().toISOString(),
					updated_at: payload.updated_at || new Date().toISOString(),
					message_count: (existing?.message_count || 0) + 2,
				}
				return [updated, ...current.filter((chat) => String(chat.id) !== String(chatId))]
			})
		} catch (error) {
			setMessages((current) => [
				...current,
				{ id: `assistant-error-${Date.now()}`, role: "assistant", content: `⚠️ ${error.message}` },
			])
			setErrorText(error.message)
		} finally {
			setSending(false)
		}
	}, [api, currentChatId, draft, sending, supportedResources])

	if (isLoading) {
		return (
			<div className="entry-screen">
				<div className="entry-card loading-card">
					<div className="mini-spinner" />
					<p>Loading MINI workspace...</p>
				</div>
			</div>
		)
	}

	if (!isAuthenticated) {
		return (
			<div className="entry-screen">
				<div className="entry-card">
					<img className="entry-logo" src="/New_logo.png" alt="MINI Agent" />
					<h1>Welcome to MINI</h1>
					<p>Enterprise-ready agent workspace for provisioning, documentation, and PR-driven infrastructure workflows.</p>
					{authError && <div className="error-banner">{authError}</div>}
					<div className="entry-actions">
						<a className="btn-primary github-login-btn" href="/auth/github">Sign in with Cargill GitHub</a>
					</div>
				</div>
			</div>
		)
	}

	return (
		<div className="mini-shell">
			<header className="top-bar">
				<div className="top-bar-left">
					<img className="top-bar-logo" src="/New_logo.png" alt="MINI Agent" />
				</div>
				<div className="top-bar-right">
					<span className="top-bar-badge">
						<svg className="top-bar-user-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
							<path d="M20 21C20 17.6863 16.4183 15 12 15C7.58172 15 4 17.6863 4 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
							<circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2"/>
						</svg>
						{githubUser}
					</span>
				</div>
			</header>

			<div className="mini-body">
				<aside className={`mini-sidebar ${sidebarOpen ? "" : "collapsed"}`}>
					<div className="sidebar-top">
						<button className="new-chat-btn" onClick={startNewChat}>✦ New Chat</button>
						<button type="button" className="sidebar-icon-toggle" onClick={() => setSidebarOpen((current) => !current)} aria-label="Close sidebar">
							<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
								<rect x="4" y="5" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.8"/>
								<path d="M10 5V19" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
							</svg>
						</button>
					</div>

					<div className="history-wrap">
						<div className="history-title">Chat History</div>
						{chats.length === 0 ? (
							<div className="history-empty">No conversations yet. Start a new chat.</div>
						) : (
							<ul className="history-list">
								{chats.map((chat) => (
									<li key={chat.id} className="history-row">
										<button className={`history-item ${String(currentChatId) === String(chat.id) ? "active" : ""}`} title={chat.title} onClick={() => loadChat(chat.id)}>
											<span>{chat.title}</span>
											<small>{formatTime(chat.updated_at)}</small>
										</button>
										<div className="history-actions">
											<button
												type="button"
												className="history-menu-btn"
												aria-label="Chat actions"
												onClick={(event) => {
													event.stopPropagation()
													setHistoryMenuId((current) => (String(current) === String(chat.id) ? null : String(chat.id)))
												}}
											>
												⋯
											</button>
											{String(historyMenuId) === String(chat.id) && (
												<div className="history-menu" onClick={(event) => event.stopPropagation()}>
													<button type="button" className="history-menu-delete" onClick={() => deleteChat(chat.id)}>
														Delete chat
													</button>
												</div>
											)}
										</div>
									</li>
								))}
							</ul>
						)}
					</div>

					<div className="sidebar-footer">
						<div className="user-card">
							<strong>Signed-in Workspace</strong>
							<span>Connected: {githubUser}</span>
						</div>
						<div className="user-actions">
							<button className="btn-danger" onClick={logout}>Logout</button>
						</div>
					</div>
				</aside>

				{!sidebarOpen && (
					<button type="button" className="sidebar-fab-toggle" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar">
						<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
							<rect x="4" y="5" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.8"/>
							<path d="M10 5V19" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
						</svg>
					</button>
				)}

				<main className="mini-main">
					<div className="main-scroll">
						<header className="main-head">
							<h2>Welcome to world of MINI</h2>
							<p>{helperText}</p>
						</header>

						{errorText && <div className="error-banner">{errorText}</div>}

						<section className="starter-grid" aria-label="MINI starters">
							{showTemplates && STARTER_CARDS.map((card) => (
								<button key={card.id} type="button" className="starter-card" onClick={() => useStarterPrompt(card.prompt)}>
									<span className="starter-tag">Starter</span>
									<h3>{card.title}</h3>
									<p>{card.description}</p>
									<div className="starter-preview" role="presentation">
										<div className="preview-title">Example chat</div>
										<div className="bubble user-bubble">{card.sampleUser}</div>
										<div className="bubble bot-bubble">{card.sampleAssistant}</div>
									</div>
								</button>
							))}
						</section>

						<section className="chat-thread" aria-label="Conversation">
							{messages.length === 0 && !showTemplates ? (
								<div className="thread-empty">No messages yet. Start typing below.</div>
							) : (
								messages.map((message, index) => (
									<MessageBubble
										key={message.id || `${message.role}-${index}`}
										message={message}
										isLatest={index === messages.length - 1 && !sending}
										onOptionClick={sendMessage}
										approvalRequirements={approvalRequirements}
										currentChatId={currentChatId}
										intakeId={null}
										onValidateApprovalUpload={uploadApprovalDocument}
									/>
								))
							)}

							{sending && (
								<div className="msg msg-assistant">
									<div className="msg-bubble typing-bubble">
										<div className="typing"><span /><span /><span /></div>
									</div>
								</div>
							)}

							<div ref={threadEndRef} />
						</section>
					</div>

					<form className="composer" onSubmit={sendMessage}>
						<div className="composer-box">
							<textarea
								ref={textareaRef}
								value={draft}
								onChange={(event) => updateComposerHeight(event.target.value)}
								onKeyDown={(event) => {
									if (event.key === "Enter" && !event.shiftKey) {
										event.preventDefault()
										sendMessage()
									}
								}}
								placeholder="Start a new conversation..."
								rows={2}
							/>
							<button type="submit" aria-label="Send message" className="send-btn" disabled={sending || !draft.trim()}>
								<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="20" height="20">
									<path d="M22 2L11 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
									<path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
								</svg>
							</button>
						</div>
					</form>
				</main>
			</div>
		</div>
	)
}

