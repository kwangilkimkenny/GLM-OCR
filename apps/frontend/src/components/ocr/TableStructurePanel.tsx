/**
 * Phase 6-D: 표 구조 인식 결과 시각화.
 * 페이지 안에서 검출된 표의 행/열 인덱스 + 셀 병합 상태를 HTML 미리보기로 보여준다.
 */
import { Layers, Code2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { RecognizedTable } from '@/libs/api'

interface TableStructurePanelProps {
	tables: RecognizedTable[]
}

// 백엔드가 생성한 표 HTML 을 dangerouslySetInnerHTML 로 주입하기 전,
// 표 구조에 필요한 태그만 허용하는 가벼운 자체 sanitizer.
// (DOMPurify 같은 무거운 의존성을 추가하지 않기 위함.)
// 정책:
//  - 허용 태그: table/thead/tbody/tfoot/tr/td/th/colgroup/col/caption/br (+ 텍스트)
//  - 그 외 태그(script/style/a/img 등)는 통째로 제거
//  - 모든 on* 이벤트 핸들러 속성 제거
//  - href/src 의 javascript:/data: 스킴 제거 (xss 회피)
const ALLOWED_TABLE_TAGS = new Set([
	'table',
	'thead',
	'tbody',
	'tfoot',
	'tr',
	'td',
	'th',
	'colgroup',
	'col',
	'caption',
	'br',
])

function sanitizeTableHtml(html: string): string {
	if (!html) return ''
	// DOMParser 로 파싱해 DOM 트리를 순회하며 허용되지 않은 노드/속성을 제거한다.
	// (브라우저 환경 전용 — 이 컴포넌트는 클라이언트에서만 렌더된다.)
	const doc = new DOMParser().parseFromString(html, 'text/html')

	const clean = (node: Node): Node | null => {
		// 텍스트 노드는 그대로 통과
		if (node.nodeType === Node.TEXT_NODE) {
			return node.cloneNode(true)
		}
		if (node.nodeType !== Node.ELEMENT_NODE) {
			return null
		}
		const el = node as Element
		const tag = el.tagName.toLowerCase()
		// script/style 등 허용되지 않은 태그는 통째로 제거 (자식도 버린다)
		if (!ALLOWED_TABLE_TAGS.has(tag)) {
			return null
		}
		const safe = doc.createElement(tag)
		// 속성 필터링: on* 이벤트 핸들러 전부 제거, href/src 의 위험 스킴 제거
		for (const attr of Array.from(el.attributes)) {
			const name = attr.name.toLowerCase()
			if (name.startsWith('on')) continue
			const value = attr.value
			if (name === 'href' || name === 'src') {
				const scheme = value.trim().toLowerCase()
				if (scheme.startsWith('javascript:') || scheme.startsWith('data:')) {
					continue
				}
			}
			safe.setAttribute(attr.name, value)
		}
		// 자식 노드도 재귀적으로 정제
		for (const child of Array.from(el.childNodes)) {
			const cleaned = clean(child)
			if (cleaned) safe.appendChild(cleaned)
		}
		return safe
	}

	const out = doc.createElement('div')
	for (const child of Array.from(doc.body.childNodes)) {
		const cleaned = clean(child)
		if (cleaned) out.appendChild(cleaned)
	}
	return out.innerHTML
}

export function TableStructurePanel({ tables }: TableStructurePanelProps) {
	const [showHtml, setShowHtml] = useState<Record<number, boolean>>({})
	// 표마다 HTML 을 한 번만 정제해 둔다 (렌더마다 재파싱 방지).
	const sanitizedHtml = useMemo(() => tables.map(t => sanitizeTableHtml(t.html)), [tables])
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
									dangerouslySetInnerHTML={{ __html: sanitizedHtml[idx] }}
								/>
							</div>
						)}
					</div>
				)
			})}
		</div>
	)
}
