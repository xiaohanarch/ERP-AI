package com.erp.ap.repo;

import com.erp.ap.domain.GrLine;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface GrLineRepo extends JpaRepository<GrLine, Long> {
    List<GrLine> findByGrIdOrderByIdAsc(Long grId);
}
