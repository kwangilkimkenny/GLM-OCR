/**
 * Phase 6-D: 표 구조 인식 결과 시각화.
 * 페이지 안에서 검출된 표의 행/열 인덱스 + 셀 병합 상태를 HTML 미리보기로 보여준다.
 */
import { Layers, Code2 } from 'lucide-react'
import { useState } from 'react'

import type { RecognizedTable } from '@/libs/api'

interface TableStructurePanelProps {
	tables: RecognizedTable[]
}

export function TableStructurePanel({ tables }: TableStructurePanelProps) {
	const [showHtml, setShowHtml] = useState<Record<number, boolean>>({})
	if (!tables || tables.length === 0) {
		return (
			<div className='p-3 text-[11px] text-gray-500 italic'>인식된 표 없음</div>
		)
	}
	return (
		<div className='p-3 space-y-2'>
			<div className='text-[11px] font-semibold text-gray-700 flex items-center gap-1.5'>
				<Layers className='size-3.5 text-amber-600' />
				표 구조 인식 (Phase 6-D)
			</div>
			{tables.map((t, idx) => {
				const cellsWithSpan = t.cells.filter(c => c.row_span > 1 || c.col_span > 1)
				return (
					<div key={idx} className='border border-amber-200 rounded bg-amber-50/40 p-2 text-[10px]'>
						<div className='flex items-center justify-between mb-1.5'>
							<div className='font-medium text-gray-700'>
								표 #{idx + 1} · 페이지 {t.page_index}
							</div>
							<span className='font-mono text-amber-700'>
								{t.rows} × {t.cols} ({t.backend})
							</span>
						</div>
						<div className='grid grid-cols-2 gap-x-2 gap-y-0.5 text-gray-600'>
							<div>셀 개수</div>
							<div className='font-mono'>{t.cells.length}</div>
							<div>병합 셀</div>
							<div className='font-mono'>{cellsWithSpan.length}</div>
							<div>표 위치 (픽셀)</div>
							<div className='font-mono'>
								[{t.table_bbox.join(', ')}]
							</div>
						</div>
						<button
							type='button'
							onClick={() => setShowHtml(prev => ({ ...prev, [idx]: !prev[idx] }))}
							className='mt-1.5 text-[9px] text-amber-700 hover:underline inline-flex items-center gap-1'>
							<Code2 className='size-3' />
							{showHtml[idx] ? 'HTML 숨기기' : 'HTML 미리보기'}
						</button>
						{showHtml[idx] && (
							<div className='mt-1.5 border rounded bg-white p-1.5 overflow-auto max-h-48'>
								<div
									className='[&_table]:border-collapse [&_td]:border [&_td]:border-gray-300 [&_td]:px-1.5 [&_td]:py-0.5 [&_td]:text-[9px]'
									dangerouslySetInnerHTML={{ __html: t.html }}
								/>
							</div>
						)}
					</div>
				)
			})}
		</div>
	)
}
