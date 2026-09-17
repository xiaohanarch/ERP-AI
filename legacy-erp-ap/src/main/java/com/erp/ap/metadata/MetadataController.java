package com.erp.ap.metadata;

import com.erp.ap.service.MetadataRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 元数据端点：实体/枚举/规则清单/操作清单。
 * 语义层（erp-ai-context）投影段实时取数 + 漂移检测的比对基准。
 */
@RestController
@RequestMapping("/metadata")
@RequiredArgsConstructor
public class MetadataController {

    private final MetadataRegistry registry;

    @GetMapping
    public Map<String, Object> full() {
        return registry.full();
    }

    @GetMapping("/entities")
    public Map<String, Object> entities() {
        return (Map<String, Object>) registry.full().get("entities");
    }

    @GetMapping("/rules")
    public Object rules() {
        return registry.full().get("rules");
    }
}
