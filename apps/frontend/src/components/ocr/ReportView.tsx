/**
 * 인쇄 친화 리포트 (5-A).
 * 새 창에 띄워 우리카드 헤더 + 추출 항목 표 + 검증 통계 + 감사 로그 노출.
 * 사용자가 cmd+P / Ctrl+P 로 PDF 저장하는 흐름.
 */
import { useEffect } from 'react'

import type {
	CrossValidationSummary,
	ExtractedFieldResult,
	GroundingSummary,
	PiiSummary,
} from '../../libs/api'
import type { AuditEntry, FieldApproval, FieldEdit } from '../../store/useOcrStore'

const FIELD_LABEL: Record<string, string> = {
	business_registration_number: '사업자등록번호',
	corporate_registration_number: '법인등록번호',
	resident_registration_number: '주민등록번호',
	foreign_registration_number: '외국인등록번호',
	bank_account_number: '계좌번호',
	account_number: '계좌번호',
	phone_number: '연락처',
	merchant_name: '상호',
	company_name: '상호',
	representative_name: '대표자명',
	business_category: '업태/종목',
	merchant_address: '사업장 주소',
	business_address: '사업장 소재지',
	beneficial_owner: '실소유자',
	ownership_percentage: '지분율',
	bank_name: '은행명',
	account_holder: '예금주',
	name: '성명',
	issue_date: '발급일자',
	issuer: '발급기관',
	license_number: '면허번호',
	establishment_date: '개업연월일',
	email: '이메일',
}

const APPROVAL_LABEL: Record<FieldApproval, string> = {
	pending: '대기',
	approved: '승인',
	rejected: '거부',
}

interface ReportViewProps {
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

export function ReportView(props: ReportViewProps) {
	useEffect(() => {
		document.title = `우리카드 OCR 분석 리포트 · ${props.fileName ?? props.taskId ?? ''}`
		// 자동으로 print dialog 열기 (사용자가 닫으면 그대로 페이지 유지)
		const t = setTimeout(() => window.print(), 300)
		return () => clearTimeout(t)
	}, [props.fileName, props.taskId])

	const total = props.fields.length
	const approvedCount = props.fields.filter(f => props.fieldApprovals[f.name] === 'approved').length
	const rejectedCount = props.fields.filter(f => props.fieldApprovals[f.name] === 'rejected').length
	const editedCount = props.fields.filter(
		f => props.fieldEdits[f.name] && props.fieldEdits[f.name].editedValue !== f.value
	).length

	const now = new Date()
	const dateStr = now.toLocaleString('ko-KR', { dateStyle: 'long', timeStyle: 'short' })

	return (
		<div className='report-root' style={{ fontFamily: '-apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif' }}>
			<style>{`
				@page { size: A4; margin: 16mm; }
				@media print {
					body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
					.no-print { display: none !important; }
				}
				.report-root {
					max-width: 210mm;
					margin: 0 auto;
					padding: 24px;
					color: #111;
					line-height: 1.5;
					font-size: 12px;
				}
				.report-title { display: flex; align-items: center; gap: 12px; border-bottom: 3px solid #1428A0; padding-bottom: 12px; margin-bottom: 16px; }
				.report-title .logo { width: 40px; height: 40px; background: #1428A0; color: white; font-weight: 700; display: flex; align-items: center; justify-content: center; border-radius: 6px; font-size: 14px; }
				.report-title h1 { margin: 0; font-size: 18px; color: #1428A0; }
				.report-title .sub { font-size: 10px; color: #666; margin-top: 2px; }
				.meta-grid { display: grid; grid-template-columns: max-content auto; gap: 4px 16px; font-size: 11px; margin-bottom: 16px; }
				.meta-grid dt { color: #666; font-weight: 500; }
				.meta-grid dd { margin: 0; }
				h2 { font-size: 13px; color: #1428A0; border-left: 4px solid #1428A0; padding-left: 8px; margin: 24px 0 8px; }
				table { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 12px; }
				th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }
				th { background: #f5f7fb; color: #1428A0; font-weight: 600; }
				.chip { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 9px; font-weight: 600; }
				.chip-ok { background: #d1fae5; color: #047857; }
				.chip-invalid, .chip-ungrounded { background: #fee2e2; color: #b91c1c; }
				.chip-unverified { background: #fef3c7; color: #92400e; }
				.chip-approved { background: #d1fae5; color: #047857; }
				.chip-rejected { background: #fee2e2; color: #b91c1c; }
				.chip-pending { background: #f3f4f6; color: #4b5563; }
				.chip-edited { background: #fef3c7; color: #92400e; margin-left: 4px; }
				.summary-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
				.summary-card { border: 1px solid #ddd; border-radius: 4px; padding: 8px 10px; }
				.summary-card .label { font-size: 9px; color: #666; }
				.summary-card .value { font-size: 16px; font-weight: 700; color: #1428A0; margin-top: 2px; }
				.footer { margin-top: 32px; font-size: 9px; color: #888; border-top: 1px solid #ddd; padding-top: 8px; }
				.audit-row { font-size: 10px; }
				.audit-row td { padding: 3px 6px; }
				.notes { color: #4b5563; font-size: 10px; }
				.btn-toolbar { display: flex; gap: 8px; justify-content: flex-end; margin-bottom: 12px; }
				.btn { padding: 4px 10px; font-size: 11px; border: 1px solid #ddd; background: white; cursor: pointer; border-radius: 4px; }
				.btn-primary { background: #1428A0; color: white; border-color: #1428A0; }
			`}</style>

			<div className='btn-toolbar no-print'>
				<button className='btn btn-primary' onClick={() => window.print()}>PDF / 인쇄</button>
				<button className='btn' onClick={() => window.close()}>닫기</button>
			</div>

			<div className='report-title'>
				<div className='logo'>우리</div>
				<div>
					<h1>우리카드 OCR 분석 리포트</h1>
					<div className='sub'>문서 특화 AI · 테스트 환경 · 생성: {dateStr}</div>
				</div>
			</div>

			<dl className='meta-grid'>
				<dt>파일</dt>
				<dd>{props.fileName ?? '—'}</dd>
				<dt>Task ID</dt>
				<dd style={{ fontFamily: 'monospace' }}>{props.taskId ?? '—'}</dd>
				<dt>문서 유형</dt>
				<dd>{props.documentType}</dd>
				<dt>처리 일시</dt>
				<dd>{dateStr}</dd>
			</dl>

			<h2>요약</h2>
			<div className='summary-row'>
				<div className='summary-card'>
					<div className='label'>추출 항목 수</div>
					<div className='value'>{total}</div>
				</div>
				<div className='summary-card'>
					<div className='label'>승인 / 거부</div>
					<div className='value'>{approvedCount} / {rejectedCount}</div>
				</div>
				<div className='summary-card'>
					<div className='label'>수정된 항목</div>
					<div className='value'>{editedCount}</div>
				</div>
				<div className='summary-card'>
					<div className='label'>근거 확인 (Grounding)</div>
					<div className='value'>
						{props.grounding
							? `${props.grounding.grounded + props.grounding.normalized} / ${props.grounding.grounded + props.grounding.normalized + props.grounding.ungrounded}`
							: '—'}
					</div>
				</div>
			</div>

			{props.crossValidation && (
				<>
					<h2>교차검증 (이중 모델)</h2>
					<table>
						<thead>
							<tr><th>일치(agreed)</th><th>불일치(conflict)</th><th>단일 엔진(single)</th><th>전체</th></tr>
						</thead>
						<tbody>
							<tr>
								<td><span className='chip chip-ok'>{props.crossValidation.agreed}</span></td>
								<td><span className='chip chip-invalid'>{props.crossValidation.conflict}</span></td>
								<td><span className='chip chip-pending'>{props.crossValidation.single}</span></td>
								<td>{props.crossValidation.total}</td>
							</tr>
						</tbody>
					</table>
				</>
			)}

			<h2>추출 항목</h2>
			<table>
				<thead>
					<tr>
						<th style={{ width: '20%' }}>필드</th>
						<th>값 (마스킹 적용된 최종)</th>
						<th style={{ width: '12%' }}>상태</th>
						<th style={{ width: '12%' }}>승인</th>
						<th style={{ width: '12%' }}>신뢰도</th>
					</tr>
				</thead>
				<tbody>
					{props.fields.map(f => {
						const edited = props.fieldEdits[f.name]?.editedValue
						const displayValue = edited ?? (f.masked_value || f.value)
						const isEdited = !!edited && edited !== f.value
						const approval = props.fieldApprovals[f.name] ?? 'pending'
						return (
							<tr key={f.name}>
								<td>
									{FIELD_LABEL[f.name] ?? f.name}
									{isEdited && <span className='chip chip-edited'>수정</span>}
								</td>
								<td style={{ fontFamily: 'monospace' }}>{displayValue}{f.notes && <div className='notes'>{f.notes}</div>}</td>
								<td><span className={`chip chip-${f.validation_status}`}>{f.validation_status}</span></td>
								<td><span className={`chip chip-${approval}`}>{APPROVAL_LABEL[approval]}</span></td>
								<td>{(f.confidence * 100).toFixed(0)}%</td>
							</tr>
						)
					})}
				</tbody>
			</table>

			{props.pii && (
				<>
					<h2>개인정보 마스킹</h2>
					<table>
						<thead>
							<tr><th>정책</th><th>민감 항목</th><th>부분 마스킹</th><th>완전 마스킹</th><th>노출</th></tr>
						</thead>
						<tbody>
							<tr>
								<td>{props.pii.masking_level}</td>
								<td>{props.pii.stats.sensitive}</td>
								<td>{props.pii.stats.masked_partial}</td>
								<td>{props.pii.stats.masked_full}</td>
								<td>{props.pii.stats.exposed}</td>
							</tr>
						</tbody>
					</table>
				</>
			)}

			<h2>감사 로그 (최근 {Math.min(props.auditLog.length, 30)}건)</h2>
			{props.auditLog.length === 0 ? (
				<div className='notes'>기록된 감사 이력이 없습니다.</div>
			) : (
				<table>
					<thead>
						<tr><th>시각</th><th>액션</th><th>필드</th><th>변경 전 → 후</th></tr>
					</thead>
					<tbody>
						{props.auditLog
							.slice(-30)
							.reverse()
							.map((a, i) => (
								<tr key={i} className='audit-row'>
									<td>{new Date(a.at).toLocaleTimeString('ko-KR')}</td>
									<td>{a.action}</td>
									<td>{FIELD_LABEL[a.fieldName] ?? a.fieldName}</td>
									<td>
										{a.from ? <code>{a.from}</code> : ''} {a.to ? <>→ <code>{a.to}</code></> : ''}
									</td>
								</tr>
							))}
					</tbody>
				</table>
			)}

			<div className='footer'>
				본 리포트는 우리카드 OCR POC 시스템에서 자동 생성되었습니다. 추출 결과는 평가자의 검수 후 우리카드 핵심시스템에 적재됩니다. 본 문서에 포함된 개인정보는 마스킹 정책 ({props.pii?.masking_level ?? 'partial'})에 따라 처리되었습니다.
			</div>
		</div>
	)
}
