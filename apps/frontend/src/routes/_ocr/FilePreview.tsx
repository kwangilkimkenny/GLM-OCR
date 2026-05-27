import { useState, useEffect, useRef, useMemo, type RefObject } from 'react'
import type { TaskResponse, UploadedFile } from './FileUpload'
import { useOcrStore } from '../../store/useOcrStore'
import PdfViewer from '@/components/ocr/PdfViewer'
import { usePdfPageMetrics } from '@/hooks/usePdfPageMetrics'
import { useFileBlockInteraction } from '@/hooks/useFileBlockInteraction'
import { usePdfScrollToBlock } from '@/hooks/usePdfScrollToBlock'
import { HighlightOverlay } from '@/components/ocr/HighlightOverlay'
import { FieldHighlightBox } from '@/components/ocr/FieldHighlightBox'

interface FilePreviewProps {
	file: UploadedFile | null
	result: TaskResponse | null
}

export function FilePreview({ file, result }: FilePreviewProps) {
	const [pdfUrl, setPdfUrl] = useState<string | null>(file?.file?.name || null)
	const viewerRef = useRef<HTMLDivElement>(null)
	const imageRef = useRef<HTMLImageElement>(null)
	const hoveredBlockId = useOcrStore(s => s.hoveredBlockId)
	const clickedBlockId = useOcrStore(s => s.clickedBlockId)
	const setHoveredBlockId = useOcrStore(s => s.setHoveredBlockId)
	const setClickedPdfBlockId = useOcrStore(s => s.setClickedPdfBlockId)
	const blocks = useOcrStore(s => s.blocks)
	const fieldHighlight = useOcrStore(s => s.fieldHighlight)
	const roiMode = useOcrStore(s => s.roiMode)
	const rois = useOcrStore(s => s.rois)
	const addRoi = useOcrStore(s => s.addRoi)
	const hoveredRoiId = useOcrStore(s => s.hoveredRoiId)

	// 박스 위치(노란 하이라이트, FieldHighlightBox, ROI)는 모두 매 렌더 img BCR 로 계산.
	// 스크롤/리사이즈/ResizeObserver 시 강제 re-render 만 트리거하면 정확한 좌표가 따라온다.
	// ResizeObserver 첫 호출이 동기로 부모 렌더 사이클 안에서 발생할 수 있어 rAF 로 defer.
	const [, setBoxRefreshTick] = useState(0)
	useEffect(() => {
		let raf = 0
		const bump = () => {
			cancelAnimationFrame(raf)
			raf = requestAnimationFrame(() => setBoxRefreshTick(t => t + 1))
		}
		const container = imageRef.current?.parentElement
		container?.addEventListener('scroll', bump)
		window.addEventListener('resize', bump)
		const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(bump) : null
		if (ro && imageRef.current) ro.observe(imageRef.current)
		return () => {
			cancelAnimationFrame(raf)
			container?.removeEventListener('scroll', bump)
			window.removeEventListener('resize', bump)
			ro?.disconnect()
		}
	}, [file?.id])

	// ROI drag-to-draw 상태 — viewport(client) 좌표만 저장. 좌표 변환은 mouseUp/render 시점에 img.getBoundingClientRect() 로.
	const [drawing, setDrawing] = useState<null | {
		startClientX: number
		startClientY: number
		currentClientX: number
		currentClientY: number
	}>(null)

	// 좌표 변환 helper: viewport client coords → 원본 픽셀 bbox.
	// img.getBoundingClientRect() 를 매 호출 시점에 측정 → 스크롤/리사이즈에 강함.
	const clientRectToOriginalBbox = (
		startX: number, startY: number, endX: number, endY: number,
	): [number, number, number, number] | null => {
		const img = imageRef.current
		if (!img) return null
		const r = img.getBoundingClientRect()
		if (r.width <= 0 || r.height <= 0) return null
		// img 표시 좌표로 변환 + clamp
		const x0i = Math.max(0, Math.min(startX, endX) - r.left)
		const y0i = Math.max(0, Math.min(startY, endY) - r.top)
		const x1i = Math.min(r.width, Math.max(startX, endX) - r.left)
		const y1i = Math.min(r.height, Math.max(startY, endY) - r.top)
		if (x1i - x0i < 4 || y1i - y0i < 4) return null
		// 표시 → 원본 픽셀 (img 의 실제 BCR 기준)
		const sx = img.naturalWidth / r.width
		const sy = img.naturalHeight / r.height
		return [
			Math.max(0, Math.round(x0i * sx)),
			Math.max(0, Math.round(y0i * sy)),
			Math.min(img.naturalWidth, Math.round(x1i * sx)),
			Math.min(img.naturalHeight, Math.round(y1i * sy)),
		]
	}

	// window 전역 mousemove/up — 컨테이너 밖에서 풀려도 안정적
	useEffect(() => {
		if (!drawing) return
		const handleMove = (e: MouseEvent) => {
			setDrawing(d =>
				d && {
					...d,
					currentClientX: e.clientX,
					currentClientY: e.clientY,
				}
			)
		}
		const handleUp = () => {
			setDrawing(d => {
				if (!d) return null
				const bbox = clientRectToOriginalBbox(
					d.startClientX, d.startClientY, d.currentClientX, d.currentClientY,
				)
				if (bbox) addRoi(bbox)
				return null
			})
		}
		window.addEventListener('mousemove', handleMove)
		window.addEventListener('mouseup', handleUp)
		return () => {
			window.removeEventListener('mousemove', handleMove)
			window.removeEventListener('mouseup', handleUp)
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [drawing, addRoi])

	const [showCopyButton, setShowCopyButton] = useState(false)

	// 获取 PDF 原始尺寸（从 metadata 或默认值）
	const pdfOriginalWidth = result?.response?.metadata?.width ?? 1654
	const pdfOriginalHeight = result?.response?.metadata?.height ?? 2339


	const isValid = useMemo(() => {
		return !isNaN(pdfOriginalWidth) && !isNaN(pdfOriginalHeight) && result?.status === 'completed'
	}, [pdfOriginalWidth, pdfOriginalHeight, result?.status])

	// 获取当前高亮的 block
	const hoveredBlock = hoveredBlockId ? blocks.find(b => b.id === hoveredBlockId) : null
	const clickedBlock = clickedBlockId ? blocks.find(b => b.id === clickedBlockId) : null
	// 优先显示点击的 block，否则显示悬停的 block
	const activeBlock = clickedBlock || hoveredBlock || null

	// 이미지 onLoad 시 박스 좌표 재계산 트리거 — cached/preload 케이스에서도 BCR 이 확정된 후 한 번 더 리렌더.
	useEffect(() => {
		const img = imageRef.current
		if (!img || file?.type === 'application/pdf') return
		const bump = () => setBoxRefreshTick(t => t + 1)
		if (img.complete && img.naturalWidth > 0) {
			// 이미 캐시되어 있어도 다음 frame 에 BCR 확정된 뒤 한 번 더 갱신
			requestAnimationFrame(bump)
		}
		img.addEventListener('load', bump)
		return () => {
			img.removeEventListener('load', bump)
		}
	}, [pdfUrl, file?.type])

	const pdfPageMetrics = usePdfPageMetrics(
		viewerRef as RefObject<HTMLDivElement>,
		pdfUrl,
		file?.type,
		isValid,
		activeBlock,
		pdfOriginalWidth,
		pdfOriginalHeight
	)

	// 使用 block 交互 hook
	const {
		handlePdfClick,
		handlePdfMouseMove,
		handlePdfMouseLeave,
		handleImageClick,
		handleImageMouseMove,
		handleImageMouseLeave
	} = useFileBlockInteraction({
		blocks,
		resultStatus: result?.status,
		setHoveredBlockId,
		setClickedBlockId: setClickedPdfBlockId,
		setShowCopyButton
	})

	// 使用滚动 hook
	usePdfScrollToBlock(
		clickedBlockId,
		clickedBlock ?? null,
		viewerRef as RefObject<HTMLDivElement>,
		pdfOriginalWidth,
		pdfOriginalHeight,
		result?.status
	)

	useEffect(() => {
		if (!hoveredBlockId && !clickedBlockId) {
			setShowCopyButton(false)
		}
	}, [hoveredBlockId, clickedBlockId])

	// 当文件变化时，创建 URL
	useEffect(() => {
		if (file && (file.type === 'application/pdf' || file.type.startsWith('image/'))) {
			const url = URL.createObjectURL(file.file)
			setPdfUrl(url)

			return () => {
				URL.revokeObjectURL(url)
			}
		} else {
			setPdfUrl(null)
		}
	}, [file])



	const renderPdfPageOverlay = (pageNumber: number) => {
		const metrics = pdfPageMetrics[pageNumber]
		if (!metrics) return null

		const scaleX = metrics.width / pdfOriginalWidth
		const scaleY = metrics.height / pdfOriginalHeight

		// 1) layout block 강조 (노랑)
		const blockOverlay =
			activeBlock && activeBlock.bbox && activeBlock.pageIndex === pageNumber ? (
				<HighlightOverlay
					block={activeBlock}
					showCopyButton={showCopyButton}
					style={{
						left: metrics.offsetX + activeBlock.bbox[0] * scaleX,
						top: metrics.offsetY + activeBlock.bbox[1] * scaleY,
						width: activeBlock.width * scaleX,
						height: activeBlock.height * scaleY
					}}
				/>
			) : null

		// 2) 추출 필드 hover 강조 (우리카드 파랑)
		const fieldOverlay =
			fieldHighlight && fieldHighlight.pageIndex === pageNumber ? (
				<FieldHighlightBox highlight={fieldHighlight} metrics={metrics} originalWidth={pdfOriginalWidth} originalHeight={pdfOriginalHeight} />
			) : null

		if (!blockOverlay && !fieldOverlay) return null
		return <>{blockOverlay}{fieldOverlay}</>
	}

	if (!file) {
		return (
			<div className='h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900'>
				<div className='text-center text-gray-500'>
					<p className='text-lg'>파일을 선택하거나 업로드하세요</p>
				</div>
			</div>
		)
	}

	return (
		<div className='pdf-preview h-full min-h-0 flex flex-col bg-white dark:bg-gray-900 overflow-hidden relative'>
			<div className='flex-1 h-full overflow-hidden' ref={viewerRef}>
				{file.type === 'application/pdf' ? (
					<PdfViewer
						file={file.file}
						className='h-full'
						renderPageOverlay={renderPdfPageOverlay}
						onPageClick={(e, pageNumber) => handlePdfClick(e, pageNumber, pdfOriginalWidth, pdfOriginalHeight)}
						onPageMouseMove={(e, pageNumber) => handlePdfMouseMove(e, pageNumber, pdfOriginalWidth, pdfOriginalHeight)}
						onPageMouseLeave={handlePdfMouseLeave}
					/>
				) : file.type.startsWith('image/') && pdfUrl ? (
					<div
						className={`h-full flex items-center justify-center p-4 overflow-auto relative ${roiMode ? 'cursor-crosshair' : 'cursor-pointer'}`}
						style={roiMode ? { boxShadow: 'inset 0 0 0 3px #1428A0', backgroundColor: 'rgba(20,40,160,0.03)' } : undefined}
						onClick={e => { if (!roiMode) handleImageClick(e) }}
						onMouseMove={e => { if (!roiMode) handleImageMouseMove(e) }}
						onMouseLeave={e => { if (!roiMode) handleImageMouseLeave(e) }}
						onMouseDown={e => {
							if (!roiMode || !imageRef.current) return
							// 이미지 표시 영역 밖(padding 등)에서 시작은 무시 → 시각/실제 영역 어긋남 방지
							const r = imageRef.current.getBoundingClientRect()
							if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
								return
							}
							e.preventDefault()
							setDrawing({
								startClientX: e.clientX,
								startClientY: e.clientY,
								currentClientX: e.clientX,
								currentClientY: e.clientY,
							})
						}}>
						{/* ROI 모드 상단 안내 배너 */}
						{roiMode && (
							<div
								className='absolute top-3 left-1/2 -translate-x-1/2 z-30 pointer-events-none px-4 py-1.5 rounded-full text-[12px] font-medium text-white shadow-lg flex items-center gap-2'
								style={{ backgroundColor: '#1428A0' }}>
								<span className='inline-flex size-2 rounded-full bg-white animate-pulse' />
								이미지 위에서 드래그하여 영역을 선택하세요
								{rois.length > 0 && (
									<span className='ml-1 text-[10px] text-white/80'>· 영역 {rois.length}개</span>
								)}
							</div>
						)}
						<img
							ref={imageRef}
							src={pdfUrl}
							alt={file.name}
							className='max-w-full max-h-full object-contain pointer-events-none'
							draggable={false}
						/>
						{/* 노란 하이라이트 박스 & 필드 하이라이트 — 매 렌더 img BCR 로 직접 계산.
						    imageScale state 는 window.resize 만 듣기 때문에 ResizeObserver/scroll/cached-load 시 stale 이 되어 박스가 어긋남.
						    ROI 박스 (아래) 와 동일한 BCR 패턴으로 정확성 보장. */}
						{(() => {
							if (roiMode) return null
							const img = imageRef.current
							const container = img?.parentElement
							if (!img || !container) return null
							if (img.naturalWidth <= 0 || img.naturalHeight <= 0) return null
							const ir = img.getBoundingClientRect()
							const cr = container.getBoundingClientRect()
							if (ir.width <= 0 || ir.height <= 0) return null
							const sx = ir.width / img.naturalWidth
							const sy = ir.height / img.naturalHeight
							const baseLeft = ir.left - cr.left
							const baseTop = ir.top - cr.top
							const blockOverlay =
								activeBlock && activeBlock.bbox ? (
									<HighlightOverlay
										block={activeBlock}
										showCopyButton={showCopyButton}
										style={{
											left: baseLeft + activeBlock.bbox[0] * sx,
											top: baseTop + activeBlock.bbox[1] * sy,
											width: activeBlock.width * sx,
											height: activeBlock.height * sy,
										}}
										copyButtonClassName='right-6'
									/>
								) : null
							const fieldOverlay = fieldHighlight ? (
								<FieldHighlightBox
									highlight={fieldHighlight}
									metrics={{
										offsetX: baseLeft,
										offsetY: baseTop,
										width: ir.width,
										height: ir.height,
									}}
									originalWidth={img.naturalWidth}
									originalHeight={img.naturalHeight}
								/>
							) : null
							if (!blockOverlay && !fieldOverlay) return null
							return <>{blockOverlay}{fieldOverlay}</>
						})()}
						{/* 이미 그려진 ROI 박스 — 매 렌더 img BCR 기준으로 정확히 변환 */}
						{(() => {
							const img = imageRef.current
							const container = img?.parentElement
							if (!img || !container) return null
							const ir = img.getBoundingClientRect()
							const cr = container.getBoundingClientRect()
							const sx = ir.width / Math.max(1, img.naturalWidth)
							const sy = ir.height / Math.max(1, img.naturalHeight)
							const baseLeft = ir.left - cr.left
							const baseTop = ir.top - cr.top
							return rois.map((r, i) => {
								const [x0, y0, x1, y1] = r.bbox
								const isHovered = hoveredRoiId === r.id
								const color =
									r.status === 'done'
										? '#10b981'
										: r.status === 'error'
										? '#ef4444'
										: '#1428A0'
								return (
									<div
										key={r.id}
										className='absolute pointer-events-none rounded transition-all'
										style={{
											left: baseLeft + x0 * sx,
											top: baseTop + y0 * sy,
											width: (x1 - x0) * sx,
											height: (y1 - y0) * sy,
											border: `${isHovered ? 3 : 2}px solid ${color}`,
											backgroundColor: isHovered
												? 'rgba(20, 40, 160, 0.14)'
												: 'rgba(20, 40, 160, 0.06)',
											boxShadow: isHovered
												? `0 0 0 2px rgba(20, 40, 160, 0.2), 0 4px 12px rgba(0,0,0,0.15)`
												: undefined,
											zIndex: isHovered ? 25 : 5,
										}}>
										<div
											className='absolute -top-5 left-0 text-[10px] font-medium px-1 rounded text-white whitespace-nowrap'
											style={{ backgroundColor: color }}>
											{i + 1}. {r.name}
										</div>
									</div>
								)
							})
						})()}
						{/* 현재 그리는 중인 임시 박스 — img BCR 기준 정확 변환 */}
						{drawing && (() => {
							const img = imageRef.current
							const container = img?.parentElement
							if (!img || !container) return null
							const ir = img.getBoundingClientRect()
							const cr = container.getBoundingClientRect()
							// 이미지 표시 영역으로 clamp 후 컨테이너 기준 좌표
							const x0v = Math.min(drawing.startClientX, drawing.currentClientX)
							const y0v = Math.min(drawing.startClientY, drawing.currentClientY)
							const x1v = Math.max(drawing.startClientX, drawing.currentClientX)
							const y1v = Math.max(drawing.startClientY, drawing.currentClientY)
							const cx0 = Math.max(ir.left, x0v) - cr.left
							const cy0 = Math.max(ir.top, y0v) - cr.top
							const cx1 = Math.min(ir.right, x1v) - cr.left
							const cy1 = Math.min(ir.bottom, y1v) - cr.top
							const left = cx0
							const top = cy0
							const width = Math.max(0, cx1 - cx0)
							const height = Math.max(0, cy1 - cy0)
							// 원본 픽셀 크기 (정확)
							const sx = img.naturalWidth / Math.max(1, ir.width)
							const sy = img.naturalHeight / Math.max(1, ir.height)
							const pxW = Math.round(width * sx)
							const pxH = Math.round(height * sy)
							return (
								<>
									<div
										className='absolute pointer-events-none border-2 border-dashed rounded-sm'
										style={{
											left,
											top,
											width,
											height,
											borderColor: '#1428A0',
											backgroundColor: 'rgba(20, 40, 160, 0.10)',
										}}
									/>
									<div
										className='absolute pointer-events-none text-[10px] font-mono text-white px-1.5 py-0.5 rounded shadow'
										style={{
											left: left + width + 4,
											top: top,
											backgroundColor: '#1428A0',
										}}>
										{pxW}×{pxH}px
									</div>
								</>
							)
						})()}
					</div>
				) : (
					<div className='h-full flex items-center justify-center text-gray-500'>
						<p>지원하지 않는 파일 형식입니다</p>
					</div>
				)}
			</div>
		</div>
	)
}
