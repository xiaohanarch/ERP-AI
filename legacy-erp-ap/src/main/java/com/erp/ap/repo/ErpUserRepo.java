package com.erp.ap.repo;

import com.erp.ap.domain.ErpUser;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ErpUserRepo extends JpaRepository<ErpUser, Long> {
    Optional<ErpUser> findByUsername(String username);
}
