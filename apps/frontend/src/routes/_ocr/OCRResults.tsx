import { useEffect, useMemo, useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { TaskResponse } from './FileUpload'
import { MarkdownPreview } from '@/components/ocr/MarkdownPreview'
import { useOcrStore } from '../../store/useOcrStore'
import { AppWindowIcon, CopyIcon, DownloadIcon, FileJsonIcon, GitCompareArrows, Activity } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { JsonPreview } from '@/components/ocr/JsonPreview'
import { QualityReportPanel } from '@/components/ocr/QualityReportPanel'
import { TableStructurePanel } from '@/components/ocr/TableStructurePanel'

interface OCRResultsProps {
	result: TaskResponse | null
	fileName?: string
}

export function OCRResults({ result, fileName }: OCRResultsProps) {
	const setBlocks = useOcrStore(s => s.setBlocks)

	const layout = useMemo(() => result?.response?.layout || [], [result?.response?.layout])
	const images = useMemo(() => result?.response?.images || {}, [result?.response?.images])

	const pageHeight = result?.response?.metadata?.height ?? 2339

	const blocks = useMemo(() => {
		if (result?.status !== 'completed') return []
		return layout
			.filter((b: any) => b.block_content && b.block_content.trim() !== '')
			.map((b: any, index: number) => {
				const blockContent = b.block_content.trim()
				let bbox: [number, number, number, number] | null = null
				let width = 0
				let height = 0
				if (b.bbox) {
					const [x1, y1, x2, y2] = b.bbox as [number, number, number, number]
					width = x2 - x1
					height = y2 - y1
					bbox = [x1, y1, x2, y2]
				}
				return {
					// block_id 가 0 일 수도 있으므로 ?? 로 null/undefined 만 폴백.
					// 폴백은 인덱스 기반의 안정적인 음수값 — 렌더마다 바뀌는 랜덤값(키/스크롤 불안정)을 쓰지 않는다.
					id: b.block_id ?? -(index + 1),
					content: blockContent,
					bbox,
					pageIndex: b.page_index ?? 1,
					isImage: blockContent.startsWith('![]('),
					width,
					height,
				}
			})
	}, [layout, images, pageHeight, result?.status])

	useEffect(() => {
		if (blocks.length > 0) setBlocks(blocks)
	}, [blocks, setBlocks])

	const response = result?.response
	const status = result?.status
	const error_message = result?.error_message
	const primaryMd = response?.full_markdown || ''
	const secondaryMd = response?.secondary_markdown || ''
	const isCompareMode = !!secondaryMd
	const cv = response?.cross_validation

	// Phase 6: 품질 진단 + 표 구조 데이터
	const qualityReports = response?.quality_reports ?? null
	const recognizedTables = response?.tables ?? null
	const hasPhase6 = (qualityReports && qualityReports.length > 0) || (recognizedTables && recognizedTables.length > 0)

	const [activeTab, setActiveTab] = useState<string>('markdown')
	useEffect(() => {
		// 결과 도착 시 compare 모드면 자동으로 비교 탭으로 이동
		if (isCompareMode && activeTab === 'markdown') {
			setActiveTab('compare')
		}
	}, [isCompareMode]) // eslint-disable-line react-hooks/exhaustive-deps

	const handleCopy = () => {
		const md = activeTab === 'secondary' ? secondaryMd : primaryMd
		if (!md) return
		navigator.clipboard.writeText(md)
		toast.success('복사 완료')
	}

	const handleDownload = () => {
		const md = activeTab === 'secondary' ? secondaryMd : primaryMd
		if (!md) return
		const blob = new Blob([md], { type: 'text/markdown' })
		const url = URL.createObjectURL(blob)
		const a = document.createElement('a')
		a.href = url
		const suffix = activeTab === 'secondary' ? '_glm' : ''
		a.download = `${fileName || 'result'}${suffix}.md`
		a.click()
		URL.revokeObjectURL(url)
		toast.success('다운로드 완료')
	}

	return (
		<div className='h-full min-h-0 flex flex-col bg-white border-l border-border'>
			<Tabs value={activeTab} onValueChange={setActiveTab} className='flex-1 min-h-0 flex flex-col overflow-hidden'>
				<div className='px-4 pt-4 pb-0 bg-white sticky top-0 z-10 flex items-center justify-between gap-2'>
					<TabsList className={`grid ${isCompareMode ? (hasPhase6 ? 'grid-cols-5' : 'grid-cols-4') : hasPhase6 ? 'grid-cols-3' : 'grid-cols-2'}`}>
						<TabsTrigger value='markdown' className='cursor-pointer'>
							<AppWindowIcon className='size-4' />
							{isCompareMode ? 'Qwen' : 'Markdown'}
						</TabsTrigger>
						{isCompareMode && (
							<>
								<TabsTrigger value='secondary' className='cursor-pointer'>
									<AppWindowIcon className='size-4' />
									GLM-OCR
								</TabsTrigger>
								<TabsTrigger value='compare' className='cursor-pointer'>
									<GitCompareArrows className='size-4' />
									비교
								</TabsTrigger>
							</>
						)}
						{hasPhase6 && (
							<TabsTrigger value='quality' className='cursor-pointer'>
								<Activity className='size-4' />
								품질/표
							</TabsTrigger>
						)}
						<TabsTrigger value='json' className='cursor-pointer'>
							<FileJsonIcon className='size-4' />JSON
						</TabsTrigger>
					</TabsList>
					{status === 'completed' && (activeTab === 'markdown' || activeTab === 'secondary') && (
						<div className='flex items-center gap-2'>
							<Button variant='outline' size='icon' className='cursor-pointer' onClick={handleCopy} title='클립보드에 복사'>
								<CopyIcon className='size-4' />
							</Button>
							<Button variant='outline' size='icon' className='cursor-pointer' onClick={handleDownload} title='Markdown 파일로 다운로드'>
								<DownloadIcon className='size-4' />
							</Button>
						</div>
					)}
				</div>

				<div className='flex-1 min-h-0 overflow-hidden'>
					<TabsContent value='markdown' className='h-full m-0 mt-0'>
						<MarkdownPane
							status={status}
							hasBlocks={blocks.length > 0}
							errorMessage={error_message}
							markdown={primaryMd}
						/>
					</TabsContent>

					{isCompareMode && (
						<TabsContent value='secondary' className='h-full m-0 mt-0 overflow-auto'>
							<div className='p-4'>
								<div className='mb-2 text-[11px] text-gray-500'>
									보조 엔진 (GLM-OCR) raw OCR 결과
								</div>
								<pre className='whitespace-pre-wrap font-mono text-xs leading-relaxed bg-gray-50 dark:bg-gray-800 p-4 rounded border border-gray-200'>
									{secondaryMd || '(보조 엔진 결과 없음)'}
								</pre>
							</div>
						</TabsContent>
					)}

					{isCompareMode && (
						<TabsContent value='compare' className='h-full m-0 mt-0 overflow-hidden'>
							<div className='h-full grid grid-cols-2 gap-px bg-gray-200'>
								<div className='bg-white overflow-auto'>
									<div className='sticky top-0 px-3 py-2 bg-[#1428A0] text-white text-[11px] font-medium flex items-center gap-2'>
										<span className='inline-flex size-4 items-center justify-center rounded bg-white text-[#1428A0] font-bold text-[9px]'>Q</span>
										Qwen2.5-VL · {primaryMd.length.toLocaleString()}자
									</div>
									<pre className='whitespace-pre-wrap font-mono text-xs leading-relaxed p-3'>
										{primaryMd}
									</pre>
								</div>
								<div className='bg-white overflow-auto'>
									<div className='sticky top-0 px-3 py-2 bg-gray-600 text-white text-[11px] font-medium flex items-center gap-2'>
										<span className='inline-flex size-4 items-center justify-center rounded bg-white text-gray-600 font-bold text-[9px]'>G</span>
										GLM-OCR · {secondaryMd.length.toLocaleString()}자
									</div>
									<pre className='whitespace-pre-wrap font-mono text-xs leading-relaxed p-3'>
										{secondaryMd}
									</pre>
								</div>
							</div>
							{cv && (
								<div className='absolute bottom-3 right-3 bg-white shadow-lg border border-gray-200 rounded px-3 py-2 text-[11px] flex items-center gap-3'>
									<span className='font-medium' style={{ color: '#1428A0' }}>교차검증 결과</span>
									<span className='text-emerald-600'>일치 {cv.agreed}</span>
									<span className='text-orange-600'>불일치 {cv.conflict}</span>
									<span className='text-gray-500'>단일 {cv.single}</span>
								</div>
							)}
						</TabsContent>
					)}

					{hasPhase6 && (
						<TabsContent value='quality' className='h-full m-0 mt-0 overflow-auto'>
							{qualityReports && qualityReports.length > 0 && (
								<QualityReportPanel reports={qualityReports} />
							)}
							{recognizedTables && recognizedTables.length > 0 && (
								<TableStructurePanel tables={recognizedTables} />
							)}
						</TabsContent>
					)}

					<TabsContent value='json' className='h-full m-0 mt-0 overflow-auto'>
						<div className='p-4'>
							{response && status === 'completed' ? (
								<div className='bg-gray-100 dark:bg-gray-800 p-4 rounded-lg overflow-auto'>
									<JsonPreview json={response} />
								</div>
							) : (
								<EmptyState text='아직 데이터가 없습니다' />
							)}
						</div>
					</TabsContent>
				</div>
			</Tabs>
		</div>
	)
}

function MarkdownPane({
	status,
	hasBlocks,
	errorMessage,
	markdown,
}: {
	status?: string
	hasBlocks: boolean
	errorMessage?: string | null
	markdown: string
}) {
	if (status === 'pending' || status === 'processing') {
		return (
			<div className='h-full flex items-center justify-center'>
				<div className='text-center'>
					<div className='inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary mb-4'></div>
					<p className='text-gray-500 dark:text-gray-400'>분석 중입니다...</p>
				</div>
			</div>
		)
	}
	if (hasBlocks && status === 'completed') return <MarkdownPreview />
	if (status === 'completed' && !markdown) return <EmptyState text='추출된 Markdown 내용이 없습니다' />
	if (status === 'failed') {
		return (
			<div className='h-full flex items-center justify-center'>
				<div className='p-4 rounded-lg text-center text-red-500 dark:text-red-400'>
					<p>분석 실패</p>
					{errorMessage && <p className='text-sm mt-2 text-gray-500 dark:text-gray-400'>{errorMessage}</p>}
				</div>
			</div>
		)
	}
	return <EmptyState text='파일을 업로드한 뒤 처리가 끝나면 결과가 표시됩니다' />
}

function EmptyState({ text }: { text: string }) {
	return (
		<div className='h-full flex items-center justify-center'>
			<div className='p-4 rounded-lg text-center text-gray-500 dark:text-gray-400'>
				<p>{text}</p>
			</div>
		</div>
	)
}
