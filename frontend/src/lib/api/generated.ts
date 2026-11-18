// 생성 파일이다. 손으로 고치지 않는다.
// 원본: 백엔드 OpenAPI(MediAgent 0.1.0, backend/scripts/export_openapi.py 결과)
// 다시 만들기: pnpm gen:api
export interface paths {
    "/chat": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 질문을 받아 진행·응급·최종 응답 이벤트를 NDJSON으로 보낸다 */
        post: operations["chat_chat_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description 서비스 상태 확인 엔드포인트. 200 OK를 반환한다.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AgeInput
         * @description 먹는 사람의 나이 구간. 한 나이면 `lower == upper`.
         */
        AgeInput: {
            /** Lower */
            lower: number;
            /**
             * Unit
             * @default 세
             * @enum {string}
             */
            unit: "세" | "개월" | "주";
            /** Upper */
            upper: number;
        };
        /** AnswerEvent */
        AnswerEvent: {
            response: components["schemas"]["ChatResponse"];
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "answer";
        };
        /**
         * Badge
         * @description 판정 줄의 배지 하나(PRD-15-01·02). `text`는 AG-08 상수 문구, `source`는 등급 불일치일 때만(파일 → 성분 API).
         */
        Badge: {
            /** Evidence Id */
            evidence_id?: string | null;
            /** Grade */
            grade?: ("1" | "2" | "M") | null;
            /** Kind */
            kind: string;
            /** Note */
            note?: string | null;
            /** Source */
            source?: ("API_DIRECT" | "FILE" | "CORPUS_QUOTE") | null;
            /** Text */
            text: string;
        };
        /**
         * Candidate
         * @description 되묻기 후보 하나(BE-06-03 A, `end_reason == CLARIFY`일 때만). 이름만 보이고 먹어도 되는지는 말하지 않는다.
         */
        Candidate: {
            /** Entp Name */
            entp_name?: string | null;
            /** Input Name */
            input_name: string;
            /** Item Seq */
            item_seq?: string | null;
            /** Matched By */
            matched_by?: string | null;
            /** Name */
            name: string;
            /** Prescription */
            prescription?: string | null;
        };
        /**
         * ChatEvent
         * @description 스트림 이벤트 한 줄(판별 유니온, 키 `type`). OpenAPI에 `ChatEvent`로 노출된다.
         */
        ChatEvent: components["schemas"]["ProgressEvent"] | components["schemas"]["EmergencyEvent"] | components["schemas"]["AnswerEvent"] | components["schemas"]["ErrorEvent"] | components["schemas"]["DoneEvent"];
        /**
         * ChatRequest
         * @description `POST /chat` 본문.
         */
        ChatRequest: {
            context?: components["schemas"]["ConversationContext"];
            /** Question */
            question: string;
        };
        /**
         * ChatResponse
         * @description `/chat` 최종 응답(`chat_response@v1`). 스트림에서는 `answer` 이벤트의 `response`로 간다.
         */
        ChatResponse: {
            /** Candidates */
            candidates?: components["schemas"]["Candidate"][];
            /** Candidates Line */
            candidates_line?: string | null;
            /** Citations */
            citations?: components["schemas"]["Citation"][];
            /** Detail */
            detail?: components["schemas"]["DetailItem"][];
            /** Disclaimer */
            disclaimer: string;
            emergency?: components["schemas"]["Emergency"] | null;
            /** End Reason */
            end_reason?: ("NORMAL" | "CLARIFY" | "REFUSE" | "LIMIT" | "VALIDATION_FALLBACK") | null;
            /** Findings */
            findings?: components["schemas"]["Finding"][];
            /** Fixed Notice */
            fixed_notice: string[];
            /** Grade Def Missing */
            grade_def_missing?: string[];
            /** Grade Defs */
            grade_defs?: components["schemas"]["GradeDef"][];
            /** Name Corrections */
            name_corrections?: components["schemas"]["NameCorrection"][];
            /** Not Checked Lines */
            not_checked_lines?: string[];
            /** Notice */
            notice?: string | null;
            /** Pharmacist Advice */
            pharmacist_advice?: string[];
            /** Pharmacist Advice Kinds */
            pharmacist_advice_kinds?: ("missing" | "grade_def")[];
            /**
             * Route
             * @enum {string}
             */
            route: "AGENT" | "REFUSE";
            /**
             * Schema Version
             * @default chat_response@v1
             * @constant
             */
            schema_version: "chat_response@v1";
            /** Sentence Refs */
            sentence_refs?: components["schemas"]["SentenceRef"][];
            /** Summary */
            summary: string | null;
        };
        /**
         * Citation
         * @description 출처 표 한 행(PRD-11-02·PRD-12 §6). `publisher`는 공식 기관 이름만(서비스 이름 금지, PRD-14). 고시 번호·판·쪽은 이 행에 둔다(BE-06-05 A).
         */
        Citation: {
            /** Dataset */
            dataset: string;
            /** Dates */
            dates: components["schemas"]["DateLine"][];
            /** Edition */
            edition?: string | null;
            /** Evidence Ids */
            evidence_ids?: string[];
            /** Notice Nos */
            notice_nos?: string[];
            /** Pages */
            pages?: string[];
            /** Publisher */
            publisher: string;
            /** Source Kind */
            source_kind?: ("API_DIRECT" | "FILE" | "CORPUS_QUOTE") | null;
        };
        /**
         * ConfirmedDrug
         * @description 되묻기 등으로 사용자가 고른 약(이름과, 있으면 품목기준코드).
         */
        ConfirmedDrug: {
            /** Item Seq */
            item_seq?: string | null;
            /** Name */
            name: string;
        };
        /**
         * ConversationContext
         * @description 같은 대화 안에서 이미 말한 값(한 입력 묶음, PRD-07-01 A). 서버는 저장·로그하지 않는다.
         */
        ConversationContext: {
            age?: components["schemas"]["AgeInput"] | null;
            /** Confirmed Drugs */
            confirmed_drugs?: components["schemas"]["ConfirmedDrug"][];
            /** Pregnant */
            pregnant?: boolean | null;
        };
        /**
         * DateLine
         * @description 날짜 한 줄(한 날짜 = 한 항목). `날짜 없음`만 `value`가 None이다. 값은 `YYYY-MM-DD` 또는 `YYYY-MM`(조회 제외).
         */
        DateLine: {
            /** Label */
            label: string;
            /** Value */
            value: string | null;
        };
        /**
         * DetailItem
         * @description 근거 상세 한 박스(AG-06 `renderer` 결과에 자료 약칭·기관·날짜 줄을 더한 것). LLM 문장 없음.
         *
         *     원문 인용(허가사항 용법용량 포함)은 `rows[]`의 원문 텍스트 칸 그대로이며 표 구조(`dose_table` 등)는 두지 않는다(BE-06-04 B).
         */
        DetailItem: {
            /** Dataset */
            dataset: string | null;
            /** Dataset Key */
            dataset_key: string | null;
            /** Dates */
            dates: components["schemas"]["DateLine"][];
            /** Drug Name */
            drug_name?: string | null;
            /** Drugs */
            drugs?: string[] | null;
            /** Easy Text Missing Line */
            easy_text_missing_line?: string | null;
            /** Evidence Id */
            evidence_id: string | null;
            /** Flags */
            flags?: string[];
            /** Item Seq */
            item_seq?: string | null;
            /** Kind */
            kind: string | null;
            /** Label Help */
            label_help?: string | null;
            /** Label Source */
            label_source?: string | null;
            /** Missing Reason */
            missing_reason?: string | null;
            /** Missing Text */
            missing_text?: string | null;
            /** Notes */
            notes?: string[];
            /** Publisher */
            publisher: string | null;
            /** Quote Notice */
            quote_notice?: string | null;
            /** Rows */
            rows?: {
                [key: string]: unknown;
            }[];
            /** Section */
            section?: string | null;
            /** Source Kind */
            source_kind: ("API_DIRECT" | "FILE" | "CORPUS_QUOTE") | null;
            /** Source Kind Label */
            source_kind_label?: string | null;
            /** Status */
            status: string | null;
        };
        /** DoneEvent */
        DoneEvent: {
            /** End Reason */
            end_reason?: ("NORMAL" | "CLARIFY" | "REFUSE" | "LIMIT" | "VALIDATION_FALLBACK") | null;
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "done";
        };
        /**
         * Emergency
         * @description 119 안내(BE-06-02 A: `end_reason`과 별개 신호). 문구·전화 링크는 상수 그대로다.
         */
        Emergency: {
            /** Tel */
            tel: string;
            /** Text */
            text: string;
            /**
             * Wide Text
             * @default 컴퓨터로 보고 있다면 휴대폰으로 119에 전화하세요.
             */
            wide_text: string;
        };
        /** EmergencyEvent */
        EmergencyEvent: {
            emergency: components["schemas"]["Emergency"];
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "emergency";
        };
        /**
         * ErrorBody
         * @description 4xx·5xx JSON 본문. 입력 값·내부 정보는 싣지 않는다.
         */
        ErrorBody: {
            /** Code */
            code: string;
            /**
             * Fields
             * @default []
             */
            fields: string[];
        };
        /** ErrorEvent */
        ErrorEvent: {
            /**
             * Code
             * @enum {string}
             */
            code: "INTERNAL_ERROR" | "TIMEOUT" | "UPSTREAM_UNAVAILABLE";
            /** Message */
            message?: string | null;
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "error";
        };
        /**
         * Finding
         * @description 판정 줄(`finalize.entries` 한 항목). 제품 줄 또는 쌍 줄(BE-06-01 A). 문구는 코드 상수.
         */
        Finding: {
            /** Age Criteria */
            age_criteria?: string[];
            /** Age Info Line */
            age_info_line?: string | null;
            /** Badges */
            badges?: components["schemas"]["Badge"][];
            /**
             * Bucket
             * @enum {string}
             */
            bucket: "found" | "not_listed" | "identified" | "unconfirmed";
            /** Drug */
            drug: string;
            /** Drugs */
            drugs?: string[];
            /** Evidence Id */
            evidence_id: string | null;
            /** Grades */
            grades?: string[];
            /** Ingredients */
            ingredients?: components["schemas"]["Ingredient"][];
            /** Input Name */
            input_name?: string | null;
            /** Kind */
            kind: string | null;
            /** Next */
            next?: string | null;
            /** Note */
            note?: string | null;
            /** Notes */
            notes?: string[];
            /** Notice Nos */
            notice_nos?: string[];
            /** Reasons */
            reasons?: string[];
            /** Reference Line */
            reference_line?: string | null;
            /** Retried */
            retried?: boolean | null;
            /** Retried Line */
            retried_line?: string | null;
            /** Searched */
            searched?: components["schemas"]["Searched"][];
            /** Source Label */
            source_label?: string | null;
            /** Sub Line */
            sub_line?: string | null;
            /**
             * Target
             * @default product
             * @enum {string}
             */
            target: "product" | "pair";
            /** Text */
            text: string;
            /**
             * Unresolved
             * @default false
             */
            unresolved: boolean;
            /** Why */
            why?: string | null;
        };
        /**
         * GradeDef
         * @description 등급 정의 블록 하나(BE-06-16 A, PRD-09-04·PRD-15-03). 원문(`text`)과 미확보 사유는 둘 중 하나만 있다.
         *
         *     제목·미확보 문구는 상수이고 원문·출처 줄은 코드가 청크에서 읽은 글자 그대로다. 원문이 없으면 출처 줄도 없다.
         */
        GradeDef: {
            /**
             * Grade
             * @enum {string}
             */
            grade: "1" | "2" | "M";
            /** Missing Reason */
            missing_reason?: ("FETCH_FAIL" | "OUT_OF_SCOPE") | null;
            /** Missing Text */
            missing_text?: string | null;
            /** Source */
            source?: string | null;
            /** Text */
            text?: string | null;
            /** Title */
            title: string;
        };
        /**
         * Ingredient
         * @description 제품 줄의 성분 하나(PRD-09-05). 성분명으로만 식별한 약은 그 성분 하나만 담는다.
         */
        Ingredient: {
            /** Code */
            code?: string | null;
            /** Code Missing Text */
            code_missing_text?: string | null;
            /** Contra Kinds */
            contra_kinds?: string[] | null;
            /** Dup */
            dup?: boolean | null;
            /** Name */
            name: string;
            /** State Labels */
            state_labels?: string[];
        };
        /**
         * NameCorrection
         * @description 오탈자 보정 고지 한 줄(AG-10-02 A). 질문에 적힌 이름 조각(`input`)을 비슷한 사전 이름(`name`) 하나로 보고 확인했다는 표시다.
         *
         *     `text`는 상수 `TYPO_CORRECTED_LINE`에 두 이름을 넣은 문장 그대로다(화면은 문장을 조립하지 않는다). 판정이 아니다.
         */
        NameCorrection: {
            /** Input */
            input: string;
            /** Name */
            name: string;
            /** Text */
            text: string;
        };
        /** ProgressEvent */
        ProgressEvent: {
            /** Label */
            label: string;
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * Stage
             * @enum {string}
             */
            stage: "drug_lookup" | "contraindication_check" | "evidence_search";
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "progress";
        };
        /** Quote */
        Quote: {
            /** End */
            end: number;
            /** Start */
            start: number;
            /** Text */
            text: string;
        };
        /** Searched */
        Searched: {
            /** Count */
            count?: number | null;
            /** Dataset */
            dataset: string | null;
        };
        /**
         * SentenceRef
         * @description 요약 문장이 인용한 근거(문장 번호 ↔ 근거 ID, 코드가 원문에서 자른 인용).
         */
        SentenceRef: {
            /** Evidence Id */
            evidence_id: string;
            /** Quotes */
            quotes?: components["schemas"]["Quote"][];
            /** Row Key */
            row_key?: string | null;
            /** Sentence Index */
            sentence_index: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    chat_chat_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatRequest"];
            };
        };
        responses: {
            /** @description NDJSON 스트림. 줄마다 ChatEvent 하나(순서 규칙은 app.api.events). */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["ChatEvent"];
                };
            };
            /** @description 요청 형식 오류(빈 질문·길이 초과·모르는 칸). 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 그래프 연결 전(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
}
