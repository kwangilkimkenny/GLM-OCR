import { useEffect, useMemo, useState } from 'react'
import {
	ShieldCheck,
	GitCompareArrows,
	ListChecks,
	MousePointer,
	Sparkles,
	Wand2,
	Layers,
	Stamp,
	FileText,
} from 'lucide-react'

import { FileUpload, type TaskResponse, type UploadedFile } from './FileUpload'
import { FilePreview } from './FilePreview'
import { OCRResults } from './OCRResults'
import {
	ExtractedFieldsPanel,
	DOCUMENT_TYPE_LABEL,
	type DocumentType,
} from '@/components/ocr/ExtractedFieldsPanel'
import { RoiPanel } from '@/components/ocr/RoiPanel'
import { useOcrStore } from '@/store/useOcrStore'
import type { EngineId, MaskingLevel } from '@/libs/api'

const ENGINE_OPTIONS: { id: EngineId; label: string; sub: string }[] = [
	{ id: 'qwen', label: 'Qwen2.5-VL', sub: '7B AWQ · vLLM' },
	{ id: 'glm-ocr', label: 'GLM-OCR', sub: '1.1B · Ollama' },
	{ id: 'both', label: '비교 모드', sub: '교차검증' },
]

const MASKING_OPTIONS: { id: MaskingLevel; label: string }[] = [
	{ id: 'partial', label: '부분 마스킹 (권장)' },
	{ id: 'full', label: '완전 마스킹' },
	{ id: 'none', label: '마스킹 없음 (감사 모드)' },
]

export function OCRPage() {
	const [uploadFile, setUploadFile] = useState<UploadedFile | null>(null)
	const [parsedResult, setParsedResult] = useState<TaskResponse | null>(null)
	const [documentType, setDocumentType] = useState<DocumentType>('auto')
	const [engine, setEngine] = useState<EngineId>('qwen')
	const [maskingLevel, setMaskingLevel] = useState<MaskingLevel>('partial')
	const [preprocess, setPreprocess] = useState(false)
	const [preprocessBinarize, setPreprocessBinarize] = useState(false)
	const [autoSegment, setAutoSegment] = useState(false)
	// Phase 6
	const [autoQuality, setAutoQuality] = useState(true)
	const [tableStructure, setTableStructure] = useState(true)
	const [rightPanel, setRightPanel] = useState<'fields' | 'roi'>('fields')
	const roiMode = useOcrStore(s => s.roiMode)
	const setRoiMode = useOcrStore(s => s.setRoiMode)
	const resetHitl = useOcrStore(s => s.resetHitl)

	useEffect(() => {
		if (roiMode) setRightPanel('roi')
	}, [roiMode])
	useEffect(() => {
		setRoiMode(rightPanel === 'roi')
	}, [rightPanel, setRoiMode])

	const status = parsedResult?.status
	const isProcessing = status === 'pending' || status === 'processing'

	const elapsed = useMemo(() => {
		const r = parsedResult?.response
		if (!r?.started_at || !r?.completed_at) return null
		const t = (new Date(r.completed_at).getTime() - new Date(r.started_at).getTime()) / 1000
		return Number.isFinite(t) ? t : null
	}, [parsedResult])

	const resultEngine = (parsedResult?.response?.metadata?.engine as EngineId | undefined) ?? null
	const pageCount = parsedResult?.response?.metadata?.total_pages
	const fieldCount = parsedResult?.response?.extracted_fields?.fields?.length ?? 0
	const cv = parsedResult?.response?.cross_validation ?? null
	const classified = parsedResult?.response?.metadata?.classified ?? null
	const segments = parsedResult?.response?.segments ?? null
	const sourceFormat = parsedResult?.response?.metadata?.source_format ?? null
	const sourceBadge = useMemo(() => {
		if (!sourceFormat) return null
		if (sourceFormat === 'hwpx' || sourceFormat === 'hwpx_native') {
			return { label: 'HWPX (native)', tip: 'HWPX 를 OCR 없이 직접 파싱 — 응답 시간 1/20, 글자 손실 0%' }
		}
		if (sourceFormat === 'hwp_via_libreoffice_to_hwpx') {
			return { label: 'HWP → HWPX', tip: 'LibreOffice 로 HWPX 자동 변환 후 네이티브 파싱' }
		}
		if (sourceFormat === 'hwp_via_libreoffice_to_pdf') {
			return { label: 'HWP → PDF', tip: 'HWPX 변환 실패 → PDF 폴백 (OCR 경로)' }
		}
		return { label: String(sourceFormat), tip: sourceFormat }
	}, [sourceFormat])
	const docElements = parsedResult?.response?.doc_elements ?? null
	const sealMatchCount = useMemo(() => {
		if (!docElements) return 0
		const all = [...(docElements.stamps ?? []), ...(docElements.signatures ?? [])]
		return all.filter(e => (e.matches ?? []).some(m => m.decision === 'match')).length
	}, [docElements])
	const stampOrSigCount = (docElements?.stamps?.length ?? 0) + (docElements?.signatures?.length ?? 0)
	// Phase 6
	const qualityReports = parsedResult?.response?.quality_reports ?? null
	const recognizedTables = parsedResult?.response?.tables ?? null
	const upscaledPages = useMemo(() => {
		if (!qualityReports) return 0
		return qualityReports.filter(q => q.needs_upscale).length
	}, [qualityReports])

	// 분류된 유형을 알아낸 후, 우측 패널은 그 유형의 expected fields 를 보여주도록.
	const effectiveDocumentType: DocumentType =
		documentType === 'auto' && classified
			? (classified.document_type as DocumentType)
			: documentType

	return (
		<div className='h-screen flex flex-col overflow-hidden bg-gray-50 dark:bg-gray-950'>
			{/* 상단 글로벌 바 */}
			<header className='shrink-0 h-12 px-4 flex items-center justify-between border-b border-border bg-white dark:bg-gray-900'>
				<div className='flex items-center gap-3'>
					<div
						className='size-7 rounded flex items-center justify-center text-white font-bold text-[11px]'
						style={{ backgroundColor: '#1428A0' }}>
						우리
					</div>
					<div>
						<div className='text-sm font-semibold leading-tight'>우리카드 OCR POC</div>
						<div className='text-[10px] text-gray-500 leading-tight'>금융권 양식 인식 데모 · 테스트 환경</div>
					</div>
				</div>

				<div className='flex items-center gap-2'>
					<span className='text-[11px] text-gray-500 mr-1'>엔진</span>
					{ENGINE_OPTIONS.map(opt => {
						const active = engine === opt.id
						return (
							<button
								key={opt.id}
								type='button'
								onClick={() => setEngine(opt.id)}
								disabled={isProcessing}
								className={`px-2.5 py-1 rounded text-[11px] border transition-colors ${
									active
										? 'text-white border-transparent'
										: 'bg-white dark:bg-gray-900 text-gray-700 border-gray-300 hover:border-[#1428A0]'
								} disabled:opacity-50 disabled:cursor-not-allowed`}
								style={active ? { backgroundColor: '#1428A0' } : undefined}>
								<div className='font-medium leading-tight flex items-center justify-center gap-1'>
									{opt.id === 'both' && <GitCompareArrows className='size-3' />}
									{opt.label}
								</div>
								<div className={`text-[9px] leading-tight ${active ? 'text-white/80' : 'text-gray-400'}`}>
									{opt.sub}
								</div>
							</button>
						)
					})}
				</div>

				<div className='flex items-center gap-4 text-[11px] text-gray-600 flex-wrap'>
					<MetricChip label='엔진' value={resultEngine ?? '—'} />
					<MetricChip label='페이지' value={pageCount != null ? String(pageCount) : '—'} />
					<MetricChip label='처리' value={elapsed != null ? `${elapsed.toFixed(1)}s` : '—'} />
					<MetricChip label='추출' value={String(fieldCount)} accent={fieldCount > 0} />
					{classified && (
						<span
							className='inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border'
							style={{ borderColor: '#1428A0', color: '#1428A0' }}
							title={`자동 분류: ${classified.document_type} (${classified.processing_time_ms}ms, raw="${classified.raw_response}")`}>
							<Sparkles className='size-3' />
							자동 분류:{' '}
							<span className='font-semibold'>
								{DOCUMENT_TYPE_LABEL[(classified.document_type as DocumentType) ?? 'freeform']}
							</span>
						</span>
					)}
					{sourceBadge && (
						<span
							className='inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-indigo-400 text-indigo-700 bg-indigo-50'
							title={sourceBadge.tip}>
							<FileText className='size-3' />
							{sourceBadge.label}
						</span>
					)}
					{cv && (
						<span
							className='inline-flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded border'
							style={{ borderColor: '#1428A0', color: '#1428A0' }}
							title={`교차검증 ${cv.agreed}/${cv.total} · 불일치 ${cv.conflict} · 단일 ${cv.single}`}>
							<GitCompareArrows className='size-3' />
							<span className='font-mono'>
								교차검증{' '}
								<span className='font-bold text-emerald-600'>{cv.agreed}</span>
								<span className='text-gray-400'>/</span>
								<span>{cv.total}</span>
							</span>
							{cv.conflict > 0 && (
								<span className='text-orange-600 ml-1'>⚠ {cv.conflict}</span>
							)}
						</span>
					)}
					{segments && segments.length > 1 && (
						<span
							className='inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-purple-400 text-purple-700'
							title={segments
								.map((s, i) => `${i + 1}. ${s.document_type} (p.${s.pages.join(',')})`)
								.join(' / ')}>
							<Layers className='size-3' /> 분할 {segments.length}건
						</span>
					)}
					{upscaledPages > 0 && qualityReports && (
						<span
							className='inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-emerald-400 text-emerald-700'
							title={qualityReports
								.filter(q => q.needs_upscale)
								.map(q => `${q.short_side}px → x${q.upscale_factor}`)
								.join(' / ')}>
							<Wand2 className='size-3' /> SR 적용 {upscaledPages}p
						</span>
					)}
					{recognizedTables && recognizedTables.length > 0 && (
						<span
							className='inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-amber-400 text-amber-700'
							title={recognizedTables
								.map(t => `p.${t.page_index} ${t.rows}x${t.cols} (${t.backend})`)
								.join(' / ')}>
							<Layers className='size-3' /> 표 {recognizedTables.length}개 (
							{recognizedTables[0].backend.startsWith('lore') ? 'LORE++' : 'gridline'})
						</span>
					)}
					{stampOrSigCount > 0 && (
						<span
							className='inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-rose-400 text-rose-700'
							title={`도장/서명 ${stampOrSigCount}건 검출 · 사전 매칭 ${sealMatchCount}건`}>
							<Stamp className='size-3' /> 도장/서명 {stampOrSigCount}
							{sealMatchCount > 0 && (
								<span className='ml-1 text-emerald-600 font-semibold'>✓ {sealMatchCount}</span>
							)}
						</span>
					)}
					<span className='inline-flex items-center gap-1 text-[10px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded'>
						<ShieldCheck className='size-3' /> 결과 N분 후 자동 삭제
					</span>
				</div>
			</header>

			<div className='flex-1 flex overflow-hidden'>
				<aside className='w-64 shrink-0 flex flex-col bg-white dark:bg-gray-900 border-r border-border'>
					<div className='p-3 border-b border-border space-y-2'>
						<div>
							<label className='block text-[11px] font-medium text-gray-600 mb-1'>문서 유형</label>
							<select
								className='w-full text-xs border border-gray-300 dark:border-gray-700 rounded px-2 py-1 bg-white dark:bg-gray-900'
								value={documentType}
								onChange={e => setDocumentType(e.target.value as DocumentType)}
								disabled={isProcessing}>
								{(Object.keys(DOCUMENT_TYPE_LABEL) as DocumentType[]).map(k => (
									<option key={k} value={k}>{DOCUMENT_TYPE_LABEL[k]}</option>
								))}
							</select>
						</div>
						<div>
							<label className='block text-[11px] font-medium text-gray-600 mb-1'>PII 마스킹</label>
							<select
								className='w-full text-xs border border-gray-300 dark:border-gray-700 rounded px-2 py-1 bg-white dark:bg-gray-900'
								value={maskingLevel}
								onChange={e => setMaskingLevel(e.target.value as MaskingLevel)}
								disabled={isProcessing}>
								{MASKING_OPTIONS.map(o => (
									<option key={o.id} value={o.id}>{o.label}</option>
								))}
							</select>
						</div>
						<div className='pt-1'>
							<label className='inline-flex items-center gap-1.5 text-[11px] text-gray-700 cursor-pointer'>
								<input
									type='checkbox'
									checked={preprocess}
									onChange={e => setPreprocess(e.target.checked)}
									disabled={isProcessing}
								/>
								<Wand2 className='size-3 text-[#1428A0]' />
								자동 전처리 (저품질 복원)
							</label>
							{preprocess && (
								<label className='ml-5 mt-1 inline-flex items-center gap-1.5 text-[10px] text-gray-600 cursor-pointer'>
									<input
										type='checkbox'
										checked={preprocessBinarize}
										onChange={e => setPreprocessBinarize(e.target.checked)}
										disabled={isProcessing}
									/>
									흑백 이진화까지
								</label>
							)}
						</div>
						<div className='pt-1'>
							<label className='inline-flex items-center gap-1.5 text-[11px] text-gray-700 cursor-pointer'>
								<input
									type='checkbox'
									checked={autoSegment}
									onChange={e => setAutoSegment(e.target.checked)}
									disabled={isProcessing}
								/>
								<Layers className='size-3 text-purple-600' />
								혼합 문서 자동 분리 (다중 페이지)
							</label>
						</div>
						<div className='pt-1'>
							<label className='inline-flex items-center gap-1.5 text-[11px] text-gray-700 cursor-pointer'>
								<input
									type='checkbox'
									checked={autoQuality}
									onChange={e => setAutoQuality(e.target.checked)}
									disabled={isProcessing}
								/>
								<Wand2 className='size-3 text-emerald-600' />
								자동 품질 진단 + SR (저해상도/그림자 보정)
							</label>
						</div>
						<div className='pt-1'>
							<label className='inline-flex items-center gap-1.5 text-[11px] text-gray-700 cursor-pointer'>
								<input
									type='checkbox'
									checked={tableStructure}
									onChange={e => setTableStructure(e.target.checked)}
									disabled={isProcessing}
								/>
								<Layers className='size-3 text-amber-600' />
								표 구조 인식 (행/열 인덱스 보장)
							</label>
						</div>
					</div>

					<div className='flex-1 min-h-0'>
						<FileUpload
							documentType={documentType}
							engine={engine}
							maskingLevel={maskingLevel}
							preprocess={preprocess}
							preprocessBinarize={preprocessBinarize}
							autoSegment={autoSegment}
							autoQuality={autoQuality}
							tableStructure={tableStructure}
							onFileUploaded={file => {
								setUploadFile(file)
								setParsedResult(null)
								resetHitl()
							}}
							onTaskStatusChange={data => setParsedResult(data)}
						/>
					</div>
				</aside>

				<main className='h-full flex-1 min-w-0 grid grid-cols-[1.1fr_1fr_0.85fr] overflow-hidden'>
					<FilePreview file={uploadFile} result={parsedResult} />
					<OCRResults result={parsedResult} fileName={uploadFile?.name} />
					<div className='h-full flex flex-col border-l border-border bg-white dark:bg-gray-900'>
						<div className='shrink-0 grid grid-cols-2 border-b border-border'>
							<button
								type='button'
								onClick={() => setRightPanel('fields')}
								className={`px-3 py-2 text-xs inline-flex items-center justify-center gap-1.5 ${
									rightPanel === 'fields'
										? 'text-white'
										: 'text-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800'
								}`}
								style={rightPanel === 'fields' ? { backgroundColor: '#1428A0' } : undefined}>
								<ListChecks className='size-3.5' /> 추출 항목
							</button>
							<button
								type='button'
								onClick={() => setRightPanel('roi')}
								className={`px-3 py-2 text-xs inline-flex items-center justify-center gap-1.5 ${
									rightPanel === 'roi'
										? 'text-white'
										: 'text-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800'
								}`}
								style={rightPanel === 'roi' ? { backgroundColor: '#1428A0' } : undefined}>
								<MousePointer className='size-3.5' /> 영역 OCR
							</button>
						</div>
						<div className='flex-1 min-h-0'>
							{rightPanel === 'fields' ? (
								<ExtractedFieldsPanel
									result={parsedResult}
									documentType={effectiveDocumentType}
								/>
							) : (
								<RoiPanel file={uploadFile} />
							)}
						</div>
					</div>
				</main>
			</div>
		</div>
	)
}

function MetricChip({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
	return (
		<span className='inline-flex items-center gap-1'>
			<span className='text-gray-400'>{label}</span>
			<span className={`font-mono ${accent ? 'text-[#1428A0] font-semibold' : 'text-gray-800'}`}>{value}</span>
		</span>
	)
}
