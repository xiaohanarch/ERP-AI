package com.erp.ap.uiapi;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/** Thymeleaf 页面路由（登录页 / 发票列表 + 内嵌 copilot + AI Command）。 */
@Controller
public class UiPageController {

    @GetMapping("/")
    public String index() {
        return "redirect:/ui/invoices";
    }

    @GetMapping("/login")
    public String login() {
        return "login";
    }

    @GetMapping("/ui/invoices")
    public String invoices() {
        return "invoices";
    }
}
