<?xml version='1.0' encoding='UTF-8'?>
<Project Type="Project" LVVersion="24008000">
	<Property Name="NI.LV.All.SourceOnly" Type="Bool">true</Property>
	<Item Name="我的电脑" Type="My Computer">
		<Property Name="server.app.propertiesEnabled" Type="Bool">true</Property>
		<Property Name="server.control.propertiesEnabled" Type="Bool">true</Property>
		<Property Name="server.tcp.enabled" Type="Bool">false</Property>
		<Property Name="server.tcp.port" Type="Int">0</Property>
		<Property Name="server.tcp.serviceName" Type="Str">我的电脑/VI服务器</Property>
		<Property Name="server.tcp.serviceName.default" Type="Str">我的电脑/VI服务器</Property>
		<Property Name="server.vi.callsEnabled" Type="Bool">true</Property>
		<Property Name="server.vi.propertiesEnabled" Type="Bool">true</Property>
		<Property Name="specify.custom.address" Type="Bool">false</Property>
		<Item Name="包装Main.vi" Type="VI" URL="../包装Main.vi"/>
		<Item Name="包装工位流水码仅查验.vi" Type="VI" URL="../包装工位流水码仅查验.vi"/>
		<Item Name="依赖关系" Type="Dependencies">
			<Item Name="vi.lib" Type="Folder">
				<Item Name="Space Constant.vi" Type="VI" URL="/&lt;vilib&gt;/dlg_ctls.llb/Space Constant.vi"/>
				<Item Name="System Exec.vi" Type="VI" URL="/&lt;vilib&gt;/Platform/system.llb/System Exec.vi"/>
			</Item>
			<Item Name="ADO Connection Close.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Connection/ADO Connection Close.vi"/>
			<Item Name="ADO Connection Create.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Connection/ADO Connection Create.vi"/>
			<Item Name="ADO Connection Destroy.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Connection/ADO Connection Destroy.vi"/>
			<Item Name="ADO Connection Execute.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Connection/ADO Connection Execute.vi"/>
			<Item Name="ADO Connection Open.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Connection/ADO Connection Open.vi"/>
			<Item Name="ADO Recordset Destroy.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Recordset/ADO Recordset Destroy.vi"/>
			<Item Name="ADO Recordset GetString.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/Recordset/ADO Recordset GetString.vi"/>
			<Item Name="Bartender打印子vi.vi" Type="VI" URL="../Bartender打印子vi.vi"/>
			<Item Name="SQL Execute.vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/SQL Execute.vi"/>
			<Item Name="SQL Fetch Data (GetString).vi" Type="VI" URL="../../6. LabSQL/LabSQL ADO functions/SQL Fetch Data (GetString).vi"/>
			<Item Name="包装工位查验.vi" Type="VI" URL="../包装工位查验.vi"/>
			<Item Name="数据库包装标记更新.vi" Type="VI" URL="../数据库包装标记更新.vi"/>
		</Item>
		<Item Name="程序生成规范" Type="Build">
			<Item Name="我的应用程序" Type="EXE">
				<Property Name="App_copyErrors" Type="Bool">true</Property>
				<Property Name="App_INI_aliasGUID" Type="Str">{0A555BC9-389D-4921-AD4E-71EA012211D7}</Property>
				<Property Name="App_INI_GUID" Type="Str">{67264714-BEBC-4BDD-A58B-121B22088862}</Property>
				<Property Name="App_serverConfig.httpPort" Type="Int">8002</Property>
				<Property Name="App_serverType" Type="Int">0</Property>
				<Property Name="Bld_autoIncrement" Type="Bool">true</Property>
				<Property Name="Bld_buildCacheID" Type="Str">{FEA10F13-66DE-496E-B410-A822F8FA989F}</Property>
				<Property Name="Bld_buildSpecName" Type="Str">我的应用程序</Property>
				<Property Name="Bld_defaultLanguage" Type="Str">ChineseS</Property>
				<Property Name="Bld_excludeInlineSubVIs" Type="Bool">true</Property>
				<Property Name="Bld_excludeLibraryItems" Type="Bool">true</Property>
				<Property Name="Bld_excludePolymorphicVIs" Type="Bool">true</Property>
				<Property Name="Bld_localDestDir" Type="Path">../builds/NI_AB_PROJECTNAME/我的应用程序</Property>
				<Property Name="Bld_localDestDirType" Type="Str">relativeToCommon</Property>
				<Property Name="Bld_modifyLibraryFile" Type="Bool">true</Property>
				<Property Name="Bld_previewCacheID" Type="Str">{2DAC8E95-B10D-4A70-923E-7D163FDD03D8}</Property>
				<Property Name="Bld_version.build" Type="Int">23</Property>
				<Property Name="Bld_version.major" Type="Int">1</Property>
				<Property Name="Destination[0].destName" Type="Str">应用程序.exe</Property>
				<Property Name="Destination[0].path" Type="Path">../builds/NI_AB_PROJECTNAME/我的应用程序/应用程序.exe</Property>
				<Property Name="Destination[0].preserveHierarchy" Type="Bool">true</Property>
				<Property Name="Destination[0].type" Type="Str">App</Property>
				<Property Name="Destination[1].destName" Type="Str">支持目录</Property>
				<Property Name="Destination[1].path" Type="Path">../builds/NI_AB_PROJECTNAME/我的应用程序/data</Property>
				<Property Name="DestinationCount" Type="Int">2</Property>
				<Property Name="Source[0].itemID" Type="Str">{08FFF4A6-95C9-43E6-B9E6-5A490B625ACA}</Property>
				<Property Name="Source[0].type" Type="Str">Container</Property>
				<Property Name="Source[1].destinationIndex" Type="Int">0</Property>
				<Property Name="Source[1].itemID" Type="Ref">/我的电脑/包装Main.vi</Property>
				<Property Name="Source[1].sourceInclusion" Type="Str">TopLevel</Property>
				<Property Name="Source[1].type" Type="Str">VI</Property>
				<Property Name="SourceCount" Type="Int">2</Property>
				<Property Name="TgtF_fileDescription" Type="Str">我的应用程序</Property>
				<Property Name="TgtF_internalName" Type="Str">我的应用程序</Property>
				<Property Name="TgtF_legalCopyright" Type="Str">版权 2024 </Property>
				<Property Name="TgtF_productName" Type="Str">我的应用程序</Property>
				<Property Name="TgtF_targetfileGUID" Type="Str">{2157C1FD-CFA3-4EB3-B13D-5B59184C6584}</Property>
				<Property Name="TgtF_targetfileName" Type="Str">应用程序.exe</Property>
				<Property Name="TgtF_versionIndependent" Type="Bool">true</Property>
			</Item>
		</Item>
	</Item>
</Project>
