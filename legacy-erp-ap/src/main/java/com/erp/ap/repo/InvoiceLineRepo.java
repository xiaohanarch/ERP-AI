package com.erp.ap.repo;

import com.erp.ap.domain.InvoiceLine;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface InvoiceLineRepo extends JpaRepository<InvoiceLine, Long> {
    List<InvoiceLine> findByInvoiceIdOrderByLineNoAsc(Long invoiceId);
}
