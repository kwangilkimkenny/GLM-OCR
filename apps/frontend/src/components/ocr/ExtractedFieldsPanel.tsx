import { useMemo, useState } from 'react'
import {
	Eye,
	EyeOff,
	ShieldCheck,
	ShieldAlert,
	ShieldQuestion,
	Info,
	GitCompareArrows,
	Check,
	X,
	Pencil,
	Download,
	RotateCcw,
	FileText,
} from 'lucide-react'
import { toast } from 'sonner'

import type { TaskResponse } from '../../routes/_ocr/FileUpload'
import type { ExtractedFieldResult, FieldValidationStatus } from '../../libs/api'
import { useOcrStore } from '../../store/useOcrStore'

function parsedTaskId(result: TaskResponse | null): string | undefined {
	if (!result?.response) return undefined
	const r = result.response as unknown as { task_id?: string | number }
	const tid = r.task_id
	return tid != null ? String(tid) : undefined
}

const ENGINE_CHIP_LABEL: Record<string, string> = {
	qwen: 'Q',
	'glm-ocr': 'G',
}
const ENGINE_CHIP_TITLE: Record<string, string> = {
	qwen: 'Qwen2.5-VL',
	'glm-ocr': 'GLM-OCR',
}

export type DocumentType =
	| 'auto'
	| 'merchant_application'
	| 'id_card'
	| 'bank_book'
	| 'business_reg'
	| 'freeform'

export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
	auto: '🔍 자동 감지',
	merchant_application: '가맹점 가입신청서',
	id_card: '신분증',
	bank_book: '통장 사본',
	business_reg: '사업자등록증',
	freeform: '자유 업로드',
}

// 필드 식별자 → 한글 라벨 (백엔드 추출기와 동기화). 백엔드에 없는 키는 placeholder 로 보여준다.
const FIELD_LABEL: Record<string, string> = {
	business_registration_number: '사업자등록번호',
	corporate_registration_number: '법인등록번호',
	resident_registration_number: '주민등록번호',
	foreign_registration_number: '외국인등록번호',
	bank_account_number: '계좌번호',
	phone_number: '연락처',
	merchant_name: '상호',
	representative_name: '대표자명',
	business_category: '업태/종목',
	beneficial_owner: '실소유자',
	ownership_percentage: '지분율',
}

// 문서 유형별 예상 필드 (결과가 없거나 추출 실패한 항목을 비어 있는 카드로 노출)
const EXPECTED_FIELDS: Record<DocumentType, string[]> = {
	auto: [],
	merchant_application: [
		'business_registration_number',
		'corporate_registration_number',
		'merchant_name',
		'representative_name',
		'business_category',
		'beneficial_owner',
		'ownership_percentage',
		'resident_registration_number',
		'bank_account_number',
		'phone_number',
	],
	id_card: ['resident_registration_number'],
	bank_book: ['bank_account_number'],
	business_reg: ['business_registration_number', 'merchant_name', 'representative_name'],
	freeform: [],
}

// 마스킹 대상 (개인정보)
const SENSITIVE_FIELDS = new Set([
	'resident_registration_number',
	'foreign_registration_number',
	'bank_account_number',
	'phone_number',
])

interface ExtractedFieldsPanelProps {
	result: TaskResponse | null
	documentType: DocumentType
}

function StatusBadge({ status }: { status: FieldValidationStatus | 'pending' }) {
	if (status === 'ok') {
		return (
			<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 border border-green-200'>
				<ShieldCheck className='size-3' /> 검증
			</span>
		)
	}
	if (status === 'ungrounded') {
		return (
			<span
				className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-700 border border-red-300'
				title='원본 OCR 에서 근거를 찾지 못함 — 환각 가능성'>
				<ShieldAlert className='size-3' /> 근거없음
			</span>
		)
	}
	if (status === 'invalid') {
		return (
			<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-700 border border-red-200'>
				<ShieldAlert className='size-3' /> 무효
			</span>
		)
	}
	if (status === 'unverified') {
		return (
			<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200'>
				<ShieldQuestion className='size-3' /> 미검증
			</span>
		)
	}
	return (
		<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500 border border-gray-200'>
			대기
		</span>
	)
}

function ConfidenceBar({ value }: { value: number }) {
	const pct = Math.max(0, Math.min(1, value)) * 100
	const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500'
	return (
		<div className='h-1.5 w-16 rounded-full bg-gray-200 overflow-hidden'>
			<div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
		</div>
	)
}

function ConsensusBadge({ consensus }: { consensus?: string | null }) {
	if (consensus === 'agreed') {
		return (
			<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200'>
				<GitCompareArrows className='size-3' /> 교차검증
			</span>
		)
	}
	if (consensus === 'conflict') {
		return (
			<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-50 text-orange-700 border border-orange-200'>
				<GitCompareArrows className='size-3' /> 엔진 간 차이
			</span>
		)
	}
	if (consensus === 'single') {
		return (
			<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-50 text-gray-600 border border-gray-200'>
				단일 엔진
			</span>
		)
	}
	return null
}

function EngineChips({ engines }: { engines?: string[] | null }) {
	if (!engines || engines.length === 0) return null
	return (
		<span className='inline-flex items-center gap-0.5'>
			{engines.map(e => (
				<span
					key={e}
					title={ENGINE_CHIP_TITLE[e] ?? e}
					className='inline-flex size-4 items-center justify-center rounded text-[9px] font-bold text-white'
					style={{ backgroundColor: e === 'qwen' ? '#1428A0' : '#6b7280' }}>
					{ENGINE_CHIP_LABEL[e] ?? e[0].toUpperCase()}
				</span>
			))}
		</span>
	)
}

function FieldCard({
	field,
	maskingOn,
}: {
	field: ExtractedFieldResult
	maskingOn: boolean
}) {
	const setFieldHighlight = useOcrStore(s => s.setFieldHighlight)
	const editEntry = useOcrStore(s => s.fieldEdits[field.name])
	const approval = useOcrStore(s => s.fieldApprovals[field.name]) ?? 'pending'
	const editField = useOcrStore(s => s.editField)
	const resetField = useOcrStore(s => s.resetField)
	const approveField = useOcrStore(s => s.approveField)
	const rejectField = useOcrStore(s => s.rejectField)

	const [editing, setEditing] = useState(false)
	const [draft, setDraft] = useState(editEntry?.editedValue ?? field.value)

	const label = FIELD_LABEL[field.name] ?? field.name
	const currentValue = editEntry?.editedValue ?? field.value
	const isEdited = !!editEntry && editEntry.editedValue !== field.value
	const shouldMask = maskingOn && SENSITIVE_FIELDS.has(field.name) && field.masked_value && !isEdited
	const displayValue = shouldMask ? field.masked_value : currentValue
	const hasBbox = Array.isArray(field.bbox) && field.bbox.length === 4 && field.page_index != null
	const lowConfidence = field.confidence < 0.5
	const isAgreed = field.consensus === 'agreed'
	const isConflict = field.consensus === 'conflict'

	const borderColor = approval === 'approved'
		? 'border-emerald-400 ring-1 ring-emerald-200'
		: approval === 'rejected'
		? 'border-red-300 opacity-70'
		: isAgreed
		? 'border-emerald-300 hover:border-emerald-500'
		: isConflict
		? 'border-orange-300 hover:border-orange-500'
		: field.validation_status === 'invalid' || field.validation_status === 'ungrounded'
		? 'border-red-300 hover:border-red-500'
		: lowConfidence
		? 'border-amber-300 hover:border-amber-500'
		: 'border-gray-200 dark:border-gray-800 hover:border-[#1428A0]'

	const commitEdit = () => {
		const v = draft.trim()
		if (!v || v === field.value) {
			setEditing(false)
			setDraft(currentValue)
			return
		}
		editField(field.name, v, field.value)
		setEditing(false)
		toast.success(`${label} 수정됨`)
	}

	const cancelEdit = () => {
		setEditing(false)
		setDraft(currentValue)
	}

	return (
		<div
			className={`rounded-md border px-3 py-2 transition-colors ${borderColor} ${
				hasBbox && !editing ? 'cursor-crosshair' : ''
			}`}
			onMouseEnter={() => {
				if (hasBbox && !editing) {
					setFieldHighlight({
						fieldName: field.name,
						label,
						value: field.value,
						bbox: field.bbox as [number, number, number, number],
						pageIndex: field.page_index as number,
					})
				}
			}}
			onMouseLeave={() => setFieldHighlight(null)}>
			<div className='flex items-center justify-between gap-2'>
				<span className='text-xs font-medium text-gray-700 dark:text-gray-200 flex items-center gap-1.5 min-w-0'>
					<span className='truncate'>{label}</span>
					<EngineChips engines={field.engines} />
					{hasBbox && <span className='text-[9px] text-[#1428A0] font-normal'>● 원본</span>}
					{isEdited && (
						<span className='text-[9px] px-1 rounded bg-amber-100 text-amber-700 border border-amber-300'>
							수정됨
						</span>
					)}
				</span>
				<div className='flex items-center gap-1 shrink-0'>
					<ConsensusBadge consensus={field.consensus} />
					<StatusBadge status={field.validation_status} />
				</div>
			</div>
			<div className='mt-1 flex items-center justify-between gap-2'>
				{editing ? (
					<input
						autoFocus
						value={draft}
						onChange={e => setDraft(e.target.value)}
						onBlur={commitEdit}
						onKeyDown={e => {
							if (e.key === 'Enter') commitEdit()
							if (e.key === 'Escape') cancelEdit()
						}}
						className='font-mono text-xs flex-1 min-w-0 border-b-2 border-[#1428A0] outline-none bg-transparent'
					/>
				) : (
					<button
						type='button'
						onClick={() => {
							setDraft(currentValue)
							setEditing(true)
						}}
						className='font-mono text-xs text-gray-900 dark:text-gray-100 truncate text-left hover:underline decoration-dotted hover:text-[#1428A0]'
						title='클릭해서 직접 수정'>
						{displayValue}
					</button>
				)}
				<ConfidenceBar value={field.confidence} />
			</div>
			{field.notes && (
				<div className='mt-1 flex items-start gap-1 text-[10px] text-[#1428A0]/80'>
					<Info className='size-2.5 mt-0.5 shrink-0' />
					<span className='truncate'>{field.notes}</span>
				</div>
			)}
			<div className='mt-1.5 flex items-center justify-between gap-1'>
				<div className='flex items-center gap-1'>
					{!editing && (
						<button
							type='button'
							onClick={() => {
								setDraft(currentValue)
								setEditing(true)
							}}
							className='inline-flex items-center gap-0.5 text-[10px] text-gray-500 hover:text-[#1428A0]'>
							<Pencil className='size-2.5' /> 수정
						</button>
					)}
					{isEdited && (
						<button
							type='button'
							onClick={() => resetField(field.name)}
							className='inline-flex items-center gap-0.5 text-[10px] text-gray-500 hover:text-red-600'>
							<RotateCcw className='size-2.5' /> 원래값
						</button>
					)}
				</div>
				<div className='flex items-center gap-0.5'>
					<button
						type='button'
						onClick={() => approveField(field.name)}
						className={`inline-flex items-center justify-center size-5 rounded ${
							approval === 'approved'
								? 'bg-emerald-500 text-white'
								: 'text-gray-400 hover:text-emerald-600 hover:bg-emerald-50'
						}`}
						title='승인'>
						<Check className='size-3' />
					</button>
					<button
						type='button'
						onClick={() => rejectField(field.name)}
						className={`inline-flex items-center justify-center size-5 rounded ${
							approval === 'rejected'
								? 'bg-red-500 text-white'
								: 'text-gray-400 hover:text-red-600 hover:bg-red-50'
						}`}
						title='거부'>
						<X className='size-3' />
					</button>
				</div>
			</div>
		</div>
	)
}

function EmptyFieldCard({ name }: { name: string }) {
	return (
		<div className='rounded-md border border-dashed border-gray-200 dark:border-gray-800 px-3 py-2'>
			<div className='flex items-center justify-between'>
				<span className='text-xs font-medium text-gray-500'>{FIELD_LABEL[name] ?? name}</span>
				<StatusBadge status='pending' />
			</div>
			<div className='mt-1 flex items-center justify-between gap-2'>
				<span className='font-mono text-xs text-gray-400 truncate'>— 미추출 —</span>
				<ConfidenceBar value={0} />
			</div>
		</div>
	)
}

export function ExtractedFieldsPanel({ result, documentType }: ExtractedFieldsPanelProps) {
	const [maskingOn, setMaskingOn] = useState(true)
	const fieldEdits = useOcrStore(s => s.fieldEdits)
	const fieldApprovals = useOcrStore(s => s.fieldApprovals)
	const auditLog = useOcrStore(s => s.auditLog)
	const approveAll = useOcrStore(s => s.approveAll)
	const resetHitl = useOcrStore(s => s.resetHitl)

	const isCompleted = result?.status === 'completed'
	const extracted = result?.response?.extracted_fields ?? null
	const grounding = result?.response?.grounding
	const extractedByName: Map<string, ExtractedFieldResult> = useMemo(() => {
		const m = new Map<string, ExtractedFieldResult>()
		extracted?.fields?.forEach(f => {
			// 같은 이름 다중 매치는 첫 것 우선 (Phase 2 후속: 신뢰도 최대값)
			if (!m.has(f.name)) m.set(f.name, f)
		})
		return m
	}, [extracted])

	const fieldNames = useMemo(() => Array.from(extractedByName.keys()), [extractedByName])
	const approvedCount = fieldNames.filter(n => fieldApprovals[n] === 'approved').length
	const rejectedCount = fieldNames.filter(n => fieldApprovals[n] === 'rejected').length
	const editedCount = fieldNames.filter(
		n => fieldEdits[n] && fieldEdits[n].editedValue !== extractedByName.get(n)?.value
	).length

	const handleExport = () => {
		const exported = {
			document_type: documentType,
			exported_at: new Date().toISOString(),
			fields: fieldNames.map(name => {
				const original = extractedByName.get(name)!
				const editedValue = fieldEdits[name]?.editedValue
				return {
					name,
					label: FIELD_LABEL[name] ?? name,
					value: editedValue ?? original.value,
					original_value: original.value,
					edited: !!editedValue && editedValue !== original.value,
					approval: fieldApprovals[name] ?? 'pending',
					confidence: original.confidence,
					validation_status: original.validation_status,
					bbox: original.bbox,
					page_index: original.page_index,
					notes: original.notes,
				}
			}),
			summary: {
				total: fieldNames.length,
				approved: approvedCount,
				rejected: rejectedCount,
				edited: editedCount,
			},
			audit_log: auditLog,
			grounding: grounding ?? null,
			pii: result?.response?.pii ?? null,
			cross_validation: result?.response?.cross_validation ?? null,
		}
		const blob = new Blob([JSON.stringify(exported, null, 2)], { type: 'application/json' })
		const url = URL.createObjectURL(blob)
		const a = document.createElement('a')
		a.href = url
		a.download = `woori-ocr-export-${Date.now()}.json`
		a.click()
		URL.revokeObjectURL(url)
		toast.success(`Export 완료 (${fieldNames.length}개 필드)`)
	}

	const handleOpenReport = () => {
		const taskId =
			(result?.response as unknown as { task_id?: string } | undefined)?.task_id ??
			parsedTaskId(result)
		const payload = {
			taskId,
			fileName: undefined,
			documentType,
			fields: Array.from(extractedByName.values()),
			fieldEdits,
			fieldApprovals,
			auditLog,
			grounding: grounding ?? null,
			crossValidation: result?.response?.cross_validation ?? null,
			pii: result?.response?.pii ?? null,
		}
		try {
			sessionStorage.setItem('woori-report-payload', JSON.stringify(payload))
		} catch (e) {
			toast.error('리포트 데이터 저장 실패')
			return
		}
		const w = window.open('/report', '_blank', 'noopener,noreferrer,width=900,height=1200')
		if (!w) toast.error('팝업 차단됨 — 브라우저 팝업 허용 후 다시 시도하세요')
	}

	// 표시 순서: 문서 유형 기대 항목 + 추출된 추가 필드(중복 제거)
	const orderedNames = useMemo(() => {
		const expected = EXPECTED_FIELDS[documentType] ?? []
		const extra = (extracted?.fields ?? [])
			.map(f => f.name)
			.filter(n => !expected.includes(n))
		return [...expected, ...Array.from(new Set(extra))]
	}, [documentType, extracted])

	const helperText = useMemo(() => {
		if (documentType === 'freeform') {
			return '자유 업로드 모드입니다. 좌측에서 문서 유형을 선택하면 항목별 자동 추출이 동작합니다.'
		}
		if (!result) return '파일을 업로드하면 추출 결과가 여기에 표시됩니다.'
		if (!isCompleted) return 'OCR 처리 중입니다. 결과가 들어오는 대로 항목이 채워집니다.'
		if (extracted?.error) return `추출 중 오류: ${extracted.error}`
		if (!extracted) return '이 결과에 대한 후처리 추출 결과가 비어 있습니다.'
		return `${extracted.fields.length}개 항목이 추출되었습니다. 신뢰도 50% 미만은 수동 확인을 권장합니다.`
	}, [documentType, result, isCompleted, extracted])

	const showCount = isCompleted && extracted ? extracted.fields.length : 0

	return (
		<div className='h-full flex flex-col border-l border-border bg-white dark:bg-gray-900'>
			<div className='px-4 py-3 border-b border-border space-y-2'>
				<div className='flex items-center justify-between'>
					<div>
						<h3 className='text-sm font-semibold'>
							추출 항목
							{showCount > 0 && (
								<span className='ml-2 text-xs font-normal text-gray-500'>{showCount}건</span>
							)}
						</h3>
						<p className='text-xs text-gray-500'>{DOCUMENT_TYPE_LABEL[documentType]}</p>
					</div>
					<button
						type='button'
						className='inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900'
						onClick={() => setMaskingOn(v => !v)}
						title='마스킹 토글 (감사 로그에 기록됩니다)'>
						{maskingOn ? <Eye className='size-4' /> : <EyeOff className='size-4' />}
						{maskingOn ? '마스킹 ON' : '마스킹 OFF'}
					</button>
				</div>
				{isCompleted && fieldNames.length > 0 && (
					<>
						<div className='flex items-center gap-1.5 text-[10px] flex-wrap'>
							<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200'>
								<Check className='size-2.5' /> 승인 {approvedCount}/{fieldNames.length}
							</span>
							{rejectedCount > 0 && (
								<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-50 text-red-700 border border-red-200'>
									<X className='size-2.5' /> 거부 {rejectedCount}
								</span>
							)}
							{editedCount > 0 && (
								<span className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200'>
									<Pencil className='size-2.5' /> 수정 {editedCount}
								</span>
							)}
							{grounding && (
								<span
									className='inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-50 text-gray-700 border border-gray-200'
									title='Grounding — 원본 OCR에서 근거가 확인된 비율'>
									근거 {grounding.grounded + grounding.normalized}/
									{grounding.grounded + grounding.normalized + grounding.ungrounded}
								</span>
							)}
						</div>
						<div className='flex items-center gap-1'>
							<button
								type='button'
								onClick={() => approveAll(fieldNames)}
								className='inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded text-white'
								style={{ backgroundColor: '#1428A0' }}>
								<Check className='size-3' /> 전체 승인
							</button>
							<button
								type='button'
								onClick={handleExport}
								className='inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-gray-300 hover:border-[#1428A0]'>
								<Download className='size-3' /> Export
							</button>
							<button
								type='button'
								onClick={handleOpenReport}
								className='inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-gray-300 hover:border-[#1428A0]'
								title='새 창에 인쇄 친화 리포트 열기 (PDF 저장은 cmd/Ctrl+P)'>
								<FileText className='size-3' /> 리포트
							</button>
							{auditLog.length > 0 && (
								<button
									type='button'
									onClick={resetHitl}
									className='inline-flex items-center gap-1 text-[11px] px-1.5 py-1 rounded text-gray-500 hover:text-red-600'
									title='수정/승인 이력 초기화'>
									<RotateCcw className='size-3' />
								</button>
							)}
						</div>
					</>
				)}
			</div>

			<div className='flex-1 overflow-y-auto px-4 py-3 space-y-2'>
				<p className='text-xs text-gray-500 leading-relaxed pb-1'>{helperText}</p>
				{documentType === 'freeform' ? (
					<div className='text-xs text-gray-400 italic'>해당 문서 유형은 추출 정의가 없습니다.</div>
				) : (
					orderedNames.map(name => {
						const field = extractedByName.get(name)
						return field ? (
							<FieldCard key={name} field={field} maskingOn={maskingOn} />
						) : (
							<EmptyFieldCard key={name} name={name} />
						)
					})
				)}
			</div>

			<div className='px-4 py-2 border-t border-border text-[10px] text-gray-400'>
				테스트 환경 · 처리 결과는 일정 시간 후 자동 삭제됩니다
			</div>
		</div>
	)
}
