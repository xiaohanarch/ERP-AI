package com.erp.ap.repo;

import com.erp.ap.domain.InvoiceTaxChange;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InvoiceTaxChangeRepo extends JpaRepository<InvoiceTaxChange, Long> {
}
