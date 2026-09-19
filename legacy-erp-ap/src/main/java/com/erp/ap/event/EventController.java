package com.erp.ap.event;

import com.erp.ap.service.OutboxService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 内部事件端点（hub 拉取 outbox）：X-Internal-Secret 校验见 AuthFilter。
 */
@RestController
@RequestMapping("/internal/events")
@RequiredArgsConstructor
public class EventController {

    private final OutboxService outboxService;

    @GetMapping
    public Map<String, Object> poll(@RequestParam(defaultValue = "20") int limit) {
        List<Map<String, Object>> events = outboxService.pollUnconsumed(Math.min(limit, 100));
        return Map.of("events", events);
    }

    @PostMapping("/ack")
    public Map<String, Object> ack(@RequestBody Map<String, Object> body) {
        Object ids = body.get("ids");
        List<Long> idList = ids instanceof List<?> list
                ? list.stream().map(v -> Long.valueOf(String.valueOf(v))).toList()
                : List.of();
        outboxService.ack(idList);
        return Map.of("acked", idList.size());
    }

    /** 事件重投（订阅方调试/补投）：注入 redelivered 标记后走首发同链路。 */
    @PostMapping("/republish")
    public Map<String, Object> republish(@RequestBody Map<String, Object> body) {
        String eventKey = String.valueOf(body.get("eventKey") == null ? "" : body.get("eventKey"));
        return outboxService.republish(eventKey);
    }
}
