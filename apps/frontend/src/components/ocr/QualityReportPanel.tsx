/**
 * Phase 6: 이미지 품질 진단 + SR 적용 결과 표시.
 * 페이지별 진단 결과를 카드 형태로 보여주고, 어떤 전처리가 자동 적용됐는지 표시.
 */
import { Wand2, Sparkles, Activity } from 'lucide-react'

import type { QualityReportEntry } from '@/libs/api'

interface QualityReportPanelProps {
	reports: QualityReportEntry[]
}

function Chip({ label, color }: { label: string; color: 'emerald' | 'amber' | 'rose' | 'sky' | 'gray' }) {
	const colorMap = {
		emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
		amber: 'bg-amber-50 text-amber-700 border-amber-200',
		rose: 'bg-rose-50 text-rose-700 border-rose-200',
		sky: 'bg-sky-50 text-sky-700 border-sky-200',
		gray: 'bg-gray-50 text-gray-600 border-gray-200',
	}
	return (
		<span className={`text-[9px] px-1.5 py-0.5 rounded border ${colorMap[color]} whitespace-nowrap`}>
			{label}
		</span>
	)
}

export function QualityReportPanel({ reports }: QualityReportPanelProps) {
	if (!reports || reports.length === 0) {
		return (
			<div className='p-3 text-[11px] text-gray-500 italic'>품질 진단 결과 없음</div>
		)
	}

	return (
		<div className='p-3 space-y-2'>
			<div className='text-[11px] font-semibold text-gray-700 flex items-center gap-1.5'>
				<Activity className='size-3.5 text-emerald-600' />
				페이지별 품질 진단 (Phase 6-A/B)
			</div>
			{reports.map((r, idx) => {
				const fileName = r.file?.split('/').pop() ?? `페이지 ${idx + 1}`
				const lowQuality =
					r.needs_upscale ||
					r.needs_deblur ||
					r.needs_deshadow ||
					r.needs_binarize ||
					r.needs_illumination_correction
				return (
					<div
						key={idx}
						className={`border rounded p-2 text-[10px] ${
							lowQuality ? 'border-amber-300 bg-amber-50/40' : 'border-gray-200 bg-white'
						}`}>
						<div className='flex items-center justify-between mb-1'>
							<div className='font-medium text-gray-700 truncate'>{fileName}</div>
							{lowQuality ? (
								<span className='inline-flex items-center gap-1 text-amber-700'>
									<Wand2 className='size-3' />
									전처리 적용
								</span>
							) : (
								<span className='inline-flex items-center gap-1 text-emerald-700'>
									<Sparkles className='size-3' />
									정상
								</span>
							)}
						</div>
						<div className='grid grid-cols-2 gap-x-2 gap-y-0.5 text-gray-600'>
							<div>해상도</div>
							<div className='font-mono'>
								{r.width} × {r.height}
								{r.dpi != null && <span className='text-gray-400 ml-1'>· {r.dpi} dpi</span>}
							</div>
							<div>글자 높이</div>
							<div className='font-mono'>
								{r.estimated_char_height != null ? `${r.estimated_char_height.toFixed(0)}px` : '—'}
							</div>
							<div>선명도 (Laplacian var)</div>
							<div className='font-mono'>{r.laplacian_var.toFixed(1)}</div>
							<div>밝기 / 대비</div>
							<div className='font-mono'>
								{r.brightness.toFixed(0)} / {r.contrast.toFixed(0)}
							</div>
							<div>조명 균일성 (낮을수록 좋음)</div>
							<div className='font-mono'>{r.shadow_score.toFixed(1)}</div>
						</div>
						<div className='mt-1.5 flex flex-wrap gap-1'>
							{r.needs_upscale && (
								<Chip label={`업스케일 ×${r.upscale_factor}`} color='emerald' />
							)}
							{r.needs_deshadow && <Chip label='그림자 제거' color='amber' />}
							{r.needs_illumination_correction && <Chip label='조명 보정' color='amber' />}
							{r.needs_deblur && <Chip label='디블러' color='rose' />}
							{r.needs_binarize && <Chip label='이진화' color='sky' />}
							{!lowQuality && <Chip label='원본 그대로' color='gray' />}
						</div>
						{r.notes.length > 0 && (
							<details className='mt-1.5 text-[9px] text-gray-500'>
								<summary className='cursor-pointer hover:text-gray-700'>진단 노트</summary>
								<ul className='ml-3 mt-0.5 list-disc'>
									{r.notes.map((n, i) => (
										<li key={i}>{n}</li>
									))}
								</ul>
							</details>
						)}
					</div>
				)
			})}
		</div>
	)
}
