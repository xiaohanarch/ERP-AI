package com.erp.ap.repo;

import com.erp.ap.domain.RolePermission;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;

public interface RolePermissionRepo extends JpaRepository<RolePermission, Long> {
    List<RolePermission> findByRoleIdIn(Collection<Long> roleIds);
}
