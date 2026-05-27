/**
 * HwpxViewer — open-hangul-ai 의 HWPXViewer 를 PdfViewer 와 동일한 props 표면으로 wrap.
 *
 * Phase 2-F: open-hangul-ai 패키지가 frontend node_modules 에 설치되기 전까지는
 * 폴백 placeholder 만 렌더한다. 패키지 추가 후 import 라인 한 줄을 풀면 활성화된다.
 *
 *   pnpm add open-hangul-ai
 *   // 그리고 아래 dynamic import 를 정적 import 로 교체
 */

import React, { useEffect, useMemo, useState } from 'react'
import { FileText } from 'lucide-react'

interface HwpxViewerProps {
	file: File | null
	className?: string
	renderPageOverlay?: (pageNumber: number) => React.ReactNode
	onPageClick?: (e: React.MouseEvent<HTMLDivElement>, pageNumber: number) => void
}

// open-hangul-ai 의 HWPXViewer 컴포넌트 동적 로드 (피어 패키지가 설치되어 있을 때만).
// 설치 안 되어 있으면 fallback 으로 안내문구 표시.
type ResolvedViewer = React.ComponentType<{
	fileUrl?: string
	file?: File | Blob
	width?: string | number
	height?: string | number
	onPageRender?: (pageNumber: number) => void
}>

function useOpenHangulViewer(): ResolvedViewer | null | 'pending' {
	const [comp, setComp] = useState<ResolvedViewer | null | 'pending'>('pending')
	useEffect(() => {
		let alive = true
		// /* @vite-ignore */ 는 반드시 `import(` 내부에 와야 Vite 가 정적 분석을 건너뛴다.
		// (밖에 두면 Vite 가 그대로 정적 해석 → 패키지 부재 시 빌드 실패)
		// @ts-ignore: 'open-hangul-ai' 는 optional peer dep — 미설치 환경에서 tsc 가 모듈 해석 실패하는 것을 무시한다.
		import(/* @vite-ignore */ 'open-hangul-ai')
			.then((mod: any) => {
				if (!alive) return
				const Viewer = mod?.HWPXViewer ?? mod?.default?.HWPXViewer ?? null
				setComp(Viewer)
			})
			.catch(() => {
				if (!alive) return
				setComp(null)
			})
		return () => {
			alive = false
		}
	}, [])
	return comp
}

export const HwpxViewer: React.FC<HwpxViewerProps> = ({
	file,
	className = '',
	renderPageOverlay,
	onPageClick,
}) => {
	const Viewer = useOpenHangulViewer()
	const fileUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
	useEffect(() => {
		return () => {
			if (fileUrl) URL.revokeObjectURL(fileUrl)
		}
	}, [fileUrl])

	if (!file) {
		return (
			<div className={`flex items-center justify-center h-full text-gray-400 text-sm ${className}`}>
				HWPX 파일을 업로드하세요
			</div>
		)
	}

	if (Viewer === 'pending') {
		return (
			<div className={`flex items-center justify-center h-full text-gray-400 text-sm ${className}`}>
				HWPX 뷰어 로딩 중…
			</div>
		)
	}

	if (!Viewer) {
		// 폴백 — open-hangul-ai 패키지가 설치되지 않은 환경
		return (
			<div className={`p-6 text-sm text-gray-500 ${className}`}>
				<div className='inline-flex items-center gap-1 mb-2 text-indigo-700'>
					<FileText className='size-4' /> HWPX (native)
				</div>
				<div className='leading-relaxed'>
					HWPX 뷰어를 사용하려면 <code>open-hangul-ai</code> 패키지를 설치하세요:
					<pre className='mt-2 p-2 bg-gray-100 dark:bg-gray-800 rounded text-xs'>pnpm add open-hangul-ai</pre>
					그동안은 백엔드가 생성한 PDF 미리보기 (`hwpx_preview.pdf`) 가 사용됩니다.
				</div>
			</div>
		)
	}

	return (
		<div
			className={className}
			onClick={(e: React.MouseEvent<HTMLDivElement>) => onPageClick?.(e, 1)}>
			<Viewer fileUrl={fileUrl ?? undefined} width='100%' height='100%' />
			{renderPageOverlay?.(1)}
		</div>
	)
}

export default HwpxViewer
