package com.erp.ap.repo;

import com.erp.ap.domain.IdempotencyRecord;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface IdempotencyRepo extends JpaRepository<IdempotencyRecord, Long> {
    Optional<IdempotencyRecord> findByBusinessKey(String businessKey);
}
