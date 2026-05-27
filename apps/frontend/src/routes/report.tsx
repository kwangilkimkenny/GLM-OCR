/**
 * /report 인쇄 친화 페이지.
 * 부모 창이 sessionStorage('woori-report-payload') 에 데이터를 넣고 새 창을 연다.
 */
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { ReportView } from '@/components/ocr/ReportView'
import type {
	CrossValidationSummary,
	ExtractedFieldResult,
	GroundingSummary,
	PiiSummary,
} from '@/libs/api'
import type { AuditEntry, FieldApproval, FieldEdit } from '@/store/useOcrStore'

interface ReportPayload {
	taskId?: string
	fileName?: string
	documentType: string
	fields: ExtractedFieldResult[]
	fieldEdits: Record<string, FieldEdit>
	fieldApprovals: Record<string, FieldApproval>
	auditLog: AuditEntry[]
	grounding?: GroundingSummary | null
	crossValidation?: CrossValidationSummary | null
	pii?: PiiSummary | null
}

function ReportPage() {
	const [payload, setPayload] = useState<ReportPayload | null>(null)
	useEffect(() => {
		try {
			const raw = sessionStorage.getItem('woori-report-payload')
			if (raw) setPayload(JSON.parse(raw))
		} catch (e) {
			// ignore
		}
	}, [])
	if (!payload) {
		return (
			<div style={{ padding: '32px', fontFamily: 'system-ui' }}>
				<h1 style={{ fontSize: '18px', color: '#1428A0' }}>리포트 데이터를 불러올 수 없습니다</h1>
				<p>이 페이지는 OCR 결과 페이지에서 "리포트" 버튼으로 열어야 합니다.</p>
			</div>
		)
	}
	return <ReportView {...payload} />
}

export const Route = createFileRoute('/report')({
	component: ReportPage,
})
