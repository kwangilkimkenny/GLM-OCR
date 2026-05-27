import type { FieldHighlight } from '@/store/useOcrStore'

interface FieldHighlightBoxProps {
	highlight: FieldHighlight
	metrics: { offsetX: number; offsetY: number; width: number; height: number }
	originalWidth: number
	originalHeight: number
}

/**
 * 추출 필드 hover 시 원본 이미지/PDF 위에 그리는 강조 박스.
 * layout block overlay(노랑)와 색상으로 구분 — 우리카드 파랑.
 */
export function FieldHighlightBox({
	highlight,
	metrics,
	originalWidth,
	originalHeight,
}: FieldHighlightBoxProps) {
	const [x0, y0, x1, y1] = highlight.bbox
	const scaleX = metrics.width / originalWidth
	const scaleY = metrics.height / originalHeight
	const left = metrics.offsetX + x0 * scaleX
	const top = metrics.offsetY + y0 * scaleY
	const width = (x1 - x0) * scaleX
	const height = (y1 - y0) * scaleY

	return (
		<div
			className='absolute pointer-events-none z-20 transition-all duration-150'
			style={{
				left: `${left}px`,
				top: `${top}px`,
				width: `${width}px`,
				height: `${height}px`,
				backgroundColor: 'rgba(20, 40, 160, 0.18)',
				border: '2.5px solid #1428A0',
				boxShadow: '0 0 0 1px rgba(20, 40, 160, 0.15), 0 6px 18px rgba(20, 40, 160, 0.25)',
				borderRadius: '4px',
			}}>
			<div
				className='absolute -top-7 left-0 px-2 py-0.5 text-[11px] font-medium text-white rounded shadow-md whitespace-nowrap'
				style={{ backgroundColor: '#1428A0' }}>
				{highlight.label} · {highlight.value.length > 30 ? highlight.value.slice(0, 30) + '…' : highlight.value}
			</div>
		</div>
	)
}
