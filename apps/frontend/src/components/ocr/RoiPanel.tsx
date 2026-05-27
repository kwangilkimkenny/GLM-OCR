import { useRef, useState } from 'react'
import { PencilLine, Play, Square, Trash2, X, Loader2, MousePointer } from 'lucide-react'

import { regionOcr, type RoiInput } from '../../libs/api'
import { useOcrStore } from '../../store/useOcrStore'
import type { UploadedFile } from '../../routes/_ocr/FileUpload'

interface RoiPanelProps {
	file: UploadedFile | null
}

export function RoiPanel({ file }: RoiPanelProps) {
	const roiMode = useOcrStore(s => s.roiMode)
	const setRoiMode = useOcrStore(s => s.setRoiMode)
	const rois = useOcrStore(s => s.rois)
	const removeRoi = useOcrStore(s => s.removeRoi)
	const renameRoi = useOcrStore(s => s.renameRoi)
	const updateRoi = useOcrStore(s => s.updateRoi)
	const clearRois = useOcrStore(s => s.clearRois)
	const setHoveredRoiId = useOcrStore(s => s.setHoveredRoiId)

	const [handwriting, setHandwriting] = useState(true)
	const [runningAll, setRunningAll] = useState(false)
	// 매 실행마다 증가하는 토큰. in-flight 응답이 돌아왔을 때 토큰이 바뀌었으면
	// (= 그 사이 재실행되었으면) stale 결과를 버려 잘못된 ROI 에 덮어쓰는 것을 막는다.
	const runTokenRef = useRef(0)

	const canRun = !!file && rois.length > 0 && !runningAll

	const handleRunAll = async () => {
		if (!file || rois.length === 0) return
		const token = ++runTokenRef.current
		setRunningAll(true)
		// 이번 실행에 보낼 ROI 의 id 를 name(고유) 기준으로 매핑해 둔다.
		// 응답은 배열 인덱스가 아니라 name 으로 다시 찾아 매칭한다 (그 사이 rois 가 바뀌어도 안전).
		const inputRois = rois
		const idByName = new Map(inputRois.map(r => [r.name, r.id]))
		inputRois.forEach(r => updateRoi(r.id, { status: 'running', error: undefined }))
		try {
			const inputs: RoiInput[] = inputRois.map(r => ({
				name: r.name,
				bbox: r.bbox,
				handwriting,
			}))
			const res = await regionOcr({ file: file.file, regions: inputs, handwriting })
			// 재실행으로 토큰이 바뀌었다면 이 응답은 stale — 무시한다.
			if (token !== runTokenRef.current) return
			res.regions.forEach((rr, i) => {
				// name 으로 매칭, 누락 시 같은 위치의 입력 ROI 로 폴백
				const id = (rr.name != null && idByName.get(rr.name)) || inputRois[i]?.id
				if (!id) return
				updateRoi(id, {
					status: rr.error ? 'error' : 'done',
					text: rr.text,
					processingTimeMs: rr.processing_time_ms,
					error: rr.error,
				})
			})
		} catch (e: any) {
			if (token !== runTokenRef.current) return
			inputRois.forEach(r =>
				updateRoi(r.id, { status: 'error', error: e?.message || 'ROI OCR 실패' })
			)
		} finally {
			if (token === runTokenRef.current) setRunningAll(false)
		}
	}

	return (
		<div className='h-full flex flex-col bg-white dark:bg-gray-900 border-l border-border'>
			<div className='px-4 py-3 border-b border-border'>
				<div className='mb-2'>
					<h3 className='text-sm font-semibold'>영역 OCR (손글씨)</h3>
					<p className='text-[11px] text-gray-500'>양식 위 손글씨 칸만 잘라서 인식</p>
				</div>
				<div
					className={`rounded-md px-2.5 py-2 mb-2 text-[11px] flex items-center justify-between gap-2 ${
						roiMode
							? 'text-white'
							: 'bg-amber-50 text-amber-800 border border-amber-200'
					}`}
					style={roiMode ? { backgroundColor: '#1428A0' } : undefined}>
					<div className='flex items-center gap-1.5 min-w-0'>
						<MousePointer className='size-3.5 shrink-0' />
						{roiMode ? (
							<span>← 좌측 이미지 위에서 드래그하세요</span>
						) : (
							<span>영역 그리기가 꺼져 있습니다</span>
						)}
					</div>
					<button
						type='button'
						onClick={() => setRoiMode(!roiMode)}
						className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${
							roiMode
								? 'border-white/40 text-white hover:bg-white/15'
								: 'border-amber-400 text-amber-700 hover:bg-amber-100'
						}`}>
						{roiMode ? 'OFF' : 'ON'}
					</button>
				</div>
				<label className='flex items-center gap-2 text-[11px] text-gray-700'>
					<input
						type='checkbox'
						checked={handwriting}
						onChange={e => setHandwriting(e.target.checked)}
					/>
					손글씨 prompt 사용 (인쇄 라벨 무시)
				</label>
				<div className='mt-2 flex items-center gap-2'>
					<button
						type='button'
						disabled={!canRun}
						onClick={handleRunAll}
						className='inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded text-white disabled:opacity-40 disabled:cursor-not-allowed'
						style={{ backgroundColor: '#1428A0' }}>
						{runningAll ? <Loader2 className='size-3.5 animate-spin' /> : <Play className='size-3.5' />}
						영역 OCR 실행
					</button>
					<button
						type='button'
						disabled={rois.length === 0 || runningAll}
						onClick={clearRois}
						className='inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 hover:border-red-400 hover:text-red-600 disabled:opacity-40'>
						<Trash2 className='size-3.5' />
						모두 지우기
					</button>
				</div>
			</div>

			<div className='flex-1 overflow-y-auto px-4 py-3 space-y-2'>
				{!file && (
					<p className='text-xs text-gray-400 italic'>
						먼저 파일을 업로드하세요.
					</p>
				)}
				{file && rois.length === 0 && (
					<p className='text-xs text-gray-500 leading-relaxed'>
						우측 상단 <strong>영역 그리기</strong>를 켠 뒤 가운데 이미지 위에서 드래그하면 영역이
						추가됩니다. 추가된 영역에 이름을 붙이고 <strong>영역 OCR 실행</strong>을 누르세요.
					</p>
				)}
				{rois.map((r, i) => (
					<div
						key={r.id}
						className={`rounded-md border px-3 py-2 transition-colors ${
							r.status === 'done'
								? 'border-emerald-300'
								: r.status === 'error'
								? 'border-red-300'
								: r.status === 'running'
								? 'border-amber-300'
								: 'border-gray-200 hover:border-[#1428A0]'
						}`}
						onMouseEnter={() => setHoveredRoiId(r.id)}
						onMouseLeave={() => setHoveredRoiId(null)}>
						<div className='flex items-center justify-between gap-2'>
							<div className='flex items-center gap-1.5 min-w-0'>
								<Square className='size-3 text-[#1428A0] shrink-0' />
								<RoiNameInput value={r.name} onChange={name => renameRoi(r.id, name)} />
							</div>
							<div className='flex items-center gap-1 shrink-0'>
								{r.status === 'running' && <Loader2 className='size-3 animate-spin text-amber-600' />}
								{r.status === 'done' && r.processingTimeMs != null && (
									<span className='text-[10px] text-gray-500 font-mono'>
										{(r.processingTimeMs / 1000).toFixed(1)}s
									</span>
								)}
								<button
									type='button'
									onClick={() => removeRoi(r.id)}
									className='p-0.5 text-gray-400 hover:text-red-500'
									title='영역 삭제'>
									<X className='size-3.5' />
								</button>
							</div>
						</div>
						<div className='mt-1 text-[10px] text-gray-400 font-mono'>
							[{i + 1}] bbox: {r.bbox.map(n => Math.round(n)).join(', ')}
						</div>
						{r.status === 'done' && r.text && (
							<pre className='mt-1.5 text-xs font-mono whitespace-pre-wrap bg-gray-50 dark:bg-gray-800 p-2 rounded text-gray-900 dark:text-gray-100'>
								{r.text || '(빈 결과)'}
							</pre>
						)}
						{r.status === 'error' && (
							<p className='mt-1 text-[11px] text-red-600'>{r.error || '오류'}</p>
						)}
					</div>
				))}
			</div>
		</div>
	)
}

function RoiNameInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
	const [editing, setEditing] = useState(false)
	const [tmp, setTmp] = useState(value)
	if (editing) {
		return (
			<input
				autoFocus
				value={tmp}
				onChange={e => setTmp(e.target.value)}
				onBlur={() => {
					setEditing(false)
					if (tmp.trim()) onChange(tmp.trim())
					else setTmp(value)
				}}
				onKeyDown={e => {
					if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
					if (e.key === 'Escape') {
						setTmp(value)
						setEditing(false)
					}
				}}
				className='text-xs font-medium border-b border-[#1428A0] outline-none min-w-0 flex-1 bg-transparent'
			/>
		)
	}
	return (
		<button
			type='button'
			onClick={() => {
				setTmp(value)
				setEditing(true)
			}}
			className='text-xs font-medium text-gray-800 dark:text-gray-100 inline-flex items-center gap-1 hover:text-[#1428A0] min-w-0'>
			<span className='truncate'>{value}</span>
			<PencilLine className='size-3 opacity-0 group-hover:opacity-100 shrink-0' />
		</button>
	)
}
