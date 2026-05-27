import axios, { AxiosError } from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

// 创建 axios 实例
const api = axios.create({
	baseURL: BASE_URL,
	timeout: 60000 // 60秒超时
})

// 请求拦截器
api.interceptors.request.use(
	config => {
		// 可以在这里添加 token 等认证信息
		return config
	},
	error => {
		return Promise.reject(error)
	}
)

// 响应拦截器
api.interceptors.response.use(
	response => {
		return response
	},
	error => {
		// 统一错误处理: 진단에 유용한 한 줄만 남기고, 호출부에서는 getApiErrorMessage 로 메시지를 얻는다.
		console.error('[API]', getApiErrorMessage(error))
		return Promise.reject(error)
	}
)

/**
 * axios/일반 에러에서 사용자에게 보여줄 메시지를 일관되게 추출한다.
 * 서버가 내려준 message → 에러 message → 폴백 순.
 */
export function getApiErrorMessage(error: unknown, fallback = '요청 처리 중 오류가 발생했습니다'): string {
	if (axios.isAxiosError(error)) {
		const data = (error as AxiosError<{ message?: string | null; error?: string | null }>).response?.data
		return data?.message || data?.error || error.message || fallback
	}
	if (error instanceof Error) return error.message || fallback
	if (typeof error === 'string') return error
	return fallback
}

// API 统一响应格式
export interface ApiResponse<T> {
	success: boolean
	data: T
	message?: string | null
	error?: string | null
}

// 上传接口返回的 data 结构
export interface UploadTaskData {
	task_id: string | number
	document_id: string
	created_at: string
	priority: string | number
	status: string
	error?: string | null
	message?: string | null
}

export interface UploadTaskResponse extends ApiResponse<UploadTaskData> {}

export type EngineId = 'qwen' | 'glm-ocr' | 'both'
export type ConsensusStatus = 'agreed' | 'conflict' | 'single'

export interface UploadTaskParams {
	file: File
	custom_url?: string
	document_type?: string
	engine?: EngineId
	masking_level?: MaskingLevel
	preprocess?: boolean
	preprocess_binarize?: boolean
	verify_seals?: boolean
	auto_segment?: boolean
	// Phase 6: 자동 품질 진단 + SR + deshadow + illumination 자동 적용
	auto_quality?: boolean
	// Phase 6-D: 표 구조 인식 (LORE++/gridline) 후처리
	table_structure?: boolean
}

// Phase 6: 페이지별 품질 진단 보고서
export interface QualityReportEntry {
	file?: string
	width: number
	height: number
	short_side: number
	dpi?: number | null
	laplacian_var: number
	brightness: number
	contrast: number
	shadow_score: number
	estimated_char_height?: number | null
	needs_upscale: boolean
	upscale_factor: number
	needs_deblur: boolean
	needs_deshadow: boolean
	needs_binarize: boolean
	needs_illumination_correction: boolean
	notes: string[]
}

// Phase 6-D: 표 구조 인식 결과
export interface TableCellEntry {
	row: number
	col: number
	row_span: number
	col_span: number
	bbox: [number, number, number, number]
	text: string
}

export interface RecognizedTable {
	page_index: number
	page_image: string
	block_index?: number
	table_bbox: [number, number, number, number]
	table_bbox_norm: [number, number, number, number]
	rows: number
	cols: number
	backend: string
	cells: TableCellEntry[]
	html: string
}

export interface ClassifiedDocumentMeta {
	document_type: string
	raw_response: string
	processing_time_ms: number
}

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed'

// 우리카드 POC: 후처리 추출 필드
export type FieldValidationStatus = 'ok' | 'invalid' | 'unverified' | 'ungrounded'
export type MaskingLevel = 'none' | 'partial' | 'full'

export interface ExtractedFieldResult {
	name: string
	value: string
	confidence: number
	bbox?: [number, number, number, number] | null
	page_index?: number | null
	validation_status: FieldValidationStatus
	masked_value?: string | null
	source_match?: string | null
	notes?: string | null
	engines?: string[] | null
	consensus?: ConsensusStatus | null
}

export interface CrossValidationSummary {
	agreed: number
	conflict: number
	single: number
	total: number
}

export interface GroundingSummary {
	grounded: number
	normalized: number
	ungrounded: number
}

export interface PiiSummary {
	masking_level: MaskingLevel
	stats: {
		sensitive: number
		masked_partial: number
		masked_full: number
		exposed: number
	}
	extra_in_text?: Array<{ kind: string; value: string; span: [number, number] }>
}

export interface SealMatch {
	reference: string
	kind: string
	similarity: number
	similarity_lo?: number
	similarity_hi?: number
	decision: 'match' | 'no_match'
}

export interface DocElement {
	bbox: [number, number, number, number] | null
	page_index?: number
	block_id?: number
	matches?: SealMatch[]
	library_empty?: boolean
}

export interface DocElements {
	stamps: DocElement[]
	signatures: DocElement[]
	tables: DocElement[]
}

export interface SegmentClassification {
	page: number
	document_type: string
	raw_response: string
	processing_time_ms: number
}

export interface SegmentResult {
	document_type: string
	pages: number[]
	page_count: number
	classifications: SegmentClassification[]
}

export interface ExtractedFieldsBlock {
	document_type: string
	fields: ExtractedFieldResult[]
	error?: string
}

// 轮询接口返回的 data 结构
export interface TaskStatusData {
	task_id: string | number
	document_id: string
	status: TaskStatus
	progress?: number
	current_stage?: string | null
	created_at: string
	started_at?: string
	completed_at?: string
	error_message?: string | null
	result_file_path?: string
	result?: {
		output_path?: string
		output_files?: string[]
		metadata?: {
			total_pages?: number
			total_text_length?: number
			word_count?: number
			processing_mode?: string
			source_type?: string
		}
		execution_time?: number
		stage_results?: any
	}
	priority: number
	full_markdown?: string
	metadata?: {
		task_id?: string
		document_id?: string
		original_filename?: string
		processing_mode?: string
		total_pages?: number
		merge_timestamp?: number
		width?: number
		height?: number
		engine?: EngineId | string
		document_type?: string
		classified?: ClassifiedDocumentMeta
		// 입력 파일 종류 + 처리 경로. UI 뱃지로 표시.
		// "hwpx" / "hwpx_native" → HWPX 네이티브 (OCR 우회)
		// "hwp_via_libreoffice_to_hwpx" → HWP → HWPX 변환 후 네이티브
		// "hwp_via_libreoffice_to_pdf"  → HWP → PDF 폴백 (OCR)
		// undefined → 기존 PDF/Image OCR 경로
		source_format?: 'hwpx' | 'hwpx_native' | 'hwp_via_libreoffice_to_hwpx' | 'hwp_via_libreoffice_to_pdf' | string
	}
	layout?: Array<{
		block_content: string
		bbox: [number, number, number, number]
		block_id: number
		text_length?: number | null
		page_index: number
	}>
	images?: Record<string, string>
	extracted_fields?: ExtractedFieldsBlock | null
	cross_validation?: CrossValidationSummary | null
	secondary_markdown?: string | null
	secondary_layout?: Array<{
		block_content: string
		bbox: [number, number, number, number] | null
		block_id: number
		page_index?: number
	}> | null
	grounding?: GroundingSummary | null
	pii?: PiiSummary | null
	doc_elements?: DocElements | null
	segments?: SegmentResult[] | null
	// Phase 6
	quality_reports?: QualityReportEntry[] | null
	tables?: RecognizedTable[] | null
}

export interface TaskStatusResponse extends ApiResponse<TaskStatusData> {}

/**
 * 上传文件并创建 OCR 任务
 * @param params 上传参数
 * @returns Promise<UploadTaskData>
 */
export async function uploadTask(params: UploadTaskParams): Promise<UploadTaskData> {
	const formData = new FormData()
	formData.append('file', params.file)
	formData.append('processing_mode', 'pipeline')
	if (params.custom_url) {
		formData.append('custom_url', params.custom_url)
	}
	if (params.document_type) {
		formData.append('document_type', params.document_type)
	}
	if (params.engine) {
		formData.append('engine', params.engine)
	}
	if (params.masking_level) {
		formData.append('masking_level', params.masking_level)
	}
	if (params.preprocess) {
		formData.append('preprocess', 'true')
	}
	if (params.preprocess_binarize) {
		formData.append('preprocess_binarize', 'true')
	}
	if (params.verify_seals === false) {
		formData.append('verify_seals', 'false')
	}
	if (params.auto_segment) {
		formData.append('auto_segment', 'true')
	}
	if (params.auto_quality) {
		formData.append('auto_quality', 'true')
	}
	if (params.table_structure) {
		formData.append('table_structure', 'true')
	}

	const response = await api.post<UploadTaskResponse>('/tasks/upload', formData)

	if (!response.data.success) {
		throw new Error(response.data.message || '업로드 실패')
	}

	return response.data.data
}

/**
 * 查询任务状态
 * @param taskId 任务 ID
 * @returns Promise<TaskStatusData>
 */
export async function getTaskStatus(taskId: string | number): Promise<TaskStatusData> {
	const response = await api.get<TaskStatusResponse>(`/tasks/${taskId}`)

	if (!response.data.success) {
		throw new Error(response.data.message || '작업 상태 조회 실패')
	}

	return response.data.data
}

// ---- ROI region OCR ----

export interface RoiInput {
	name: string
	bbox: [number, number, number, number]  // 원본 픽셀 좌표
	handwriting?: boolean
}

export interface RoiResult {
	name: string
	bbox?: [number, number, number, number]
	text?: string
	processing_time_ms?: number
	snapshot_path?: string | null
	error?: string
}

export interface RegionOcrResponse {
	task_id: string
	image_path: string
	region_count: number
	regions: RoiResult[]
}

export async function regionOcr(params: {
	file: File
	regions: RoiInput[]
	handwriting?: boolean
}): Promise<RegionOcrResponse> {
	const formData = new FormData()
	formData.append('file', params.file)
	formData.append('regions', JSON.stringify(params.regions))
	formData.append('handwriting', String(params.handwriting ?? true))
	const response = await api.post<ApiResponse<RegionOcrResponse>>('/tasks/region-ocr', formData)
	if (!response.data.success) throw new Error(response.data.message || 'ROI OCR 실패')
	return response.data.data
}

export default api
