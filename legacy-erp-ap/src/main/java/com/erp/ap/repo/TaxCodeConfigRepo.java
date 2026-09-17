package com.erp.ap.repo;

import com.erp.ap.domain.TaxCodeConfig;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface TaxCodeConfigRepo extends JpaRepository<TaxCodeConfig, Long> {
    Optional<TaxCodeConfig> findByTenantIdAndRegion(String tenantId, String region);
}
